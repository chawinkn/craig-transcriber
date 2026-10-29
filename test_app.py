import io
import json
import os
import sys
import tempfile
import time
import types
import unittest
from unittest import mock
import wave
import zipfile
from pathlib import Path

from project import Project
import convert_model
from transcribe import MODEL_FILES, EngineCrashed, Job, ProcessEngine, WhisperEngine, lines_from_segments, looks_hallucinated, model_catalog


def wav(seconds=0.2):
    b = io.BytesIO()
    with wave.open(b, "wb") as w:
        w.setnchannels(1), w.setsampwidth(2), w.setframerate(8000)
        w.writeframes(b"\0\0" * int(8000 * seconds))
    return b.getvalue()


def upload(p, name, data):
    return p.add_upload(io.BytesIO(data), len(data), name)


def texts(p):
    return [(l["spk"], l["text"]) for l in p.state()["lines"]]


def seg(start, text, conf=-0.3, no_speech=0.0):
    return {"start": start, "end": start + 1, "text": text, "conf": conf, "no_speech": no_speech}


class ProjectTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name) / "work"
        self.p = Project(self.dir)
        self.addCleanup(self.tmp.cleanup)

    def two(self):
        upload(self.p, "1-a.wav", wav()), upload(self.p, "2-b.wav", wav())
        a, b = [s["id"] for s in self.p.state()["speakers"]]
        self.p.replace_lines(a, [seg(0, "hello"), seg(5, "world")])
        self.p.replace_lines(b, [seg(2, "other")])
        return a, b

    def test_upload_and_dedup(self):
        self.assertEqual(upload(self.p, "1-tester.wav", wav()), ["tester"])
        self.assertEqual(upload(self.p, "2-tester.wav", wav()), ["tester (2)"])
        sid = self.p.state()["speakers"][0]["id"]
        self.assertEqual(self.p.audio(sid)[1], "audio/wav")
        self.assertEqual(self.p.speaker(sid)["name"], "tester")

    def test_zip_and_bad_uploads(self):
        b = io.BytesIO()
        with zipfile.ZipFile(b, "w") as z:
            z.writestr("1-a.wav", wav()), z.writestr("2-b.wav", wav()), z.writestr("notes.txt", "x")
        self.assertEqual(upload(self.p, "rec.zip", b.getvalue()), ["a", "b"])
        with self.assertRaisesRegex(ValueError, "not an audio file or .zip"):
            upload(self.p, "x.txt", b"hi")
        with self.assertRaisesRegex(ValueError, "not a valid .zip"):
            upload(self.p, "bad.zip", b"not a zip")
        with self.assertRaisesRegex(ValueError, "No audio files were found inside empty.zip"):
            e = io.BytesIO()
            zipfile.ZipFile(e, "w").writestr("a.txt", "x")
            upload(self.p, "empty.zip", e.getvalue())
        self.assertEqual(list(self.dir.glob("*.tmp")), [])

    def test_edits_persist(self):
        a, b = self.two()
        l1 = self.p.state()["lines"][0]["id"]
        self.p.edit_lines([{"id": l1, "text": "HELLO", "ok": True, "start": 0.123, "end": -1}, {"id": "nope"}])
        new = self.p.add_line_after(l1)
        self.assertIsNone(self.p.add_line_after("nope"))
        self.p.delete_line(self.p.state()["lines"][-1]["id"])
        self.p.rename_speaker(a, "  Alice ")
        self.p.rename_speaker(b, "   ")
        q = Project(self.dir)
        first = q.state()["lines"][0]
        self.assertEqual((first["text"], first["ok"], first["start"], first["end"]), ("HELLO", True, 0.12, 1.0))
        self.assertIn(new["id"], [l["id"] for l in q.state()["lines"]])
        self.assertEqual([s["name"] for s in q.state()["speakers"]], ["Alice", "b"])
        path = q.audio(b)[0]
        q.remove_speaker(b)
        self.assertFalse(path.exists())
        r = Project(self.dir)
        self.assertEqual([s["id"] for s in r.state()["speakers"]], [a])
        self.assertTrue(all(l["spk"] == a for l in r.state()["lines"]))

    def test_replace_lines_only_that_speaker(self):
        a, b = self.two()
        self.p.replace_lines(a, [seg(9, "new")], duration=12.5)
        self.assertEqual(texts(Project(self.dir)), [(b, "other"), (a, "new")])
        self.assertEqual(self.p.speaker(a)["duration"], 12.5)
        self.p.replace_lines("gone", [seg(0, "x")])
        self.assertEqual(len(self.p.state()["lines"]), 2)

    def test_touched_speakers_are_reported(self):
        a, b = self.two()
        touched = lambda: {s["id"]: s["touched"] for s in self.p.state()["speakers"]}
        self.assertEqual(touched(), {a: False, b: False})
        la, lb = [l["id"] for l in self.p.state()["lines"] if l["text"] in ("hello", "other")]
        self.p.edit_lines([{"id": la, "text": "hello there"}, {"id": lb, "ok": True}])
        self.assertEqual(touched(), {a: True, b: True})
        self.p.edit_lines([{"id": la, "text": "hello"}, {"id": lb, "ok": False}])
        self.assertEqual(touched(), {a: False, b: False})
        self.p.edit_lines([{"id": self.p.add_line_after(lb)["id"], "text": "added by hand"}])
        self.assertEqual(touched(), {a: False, b: True})
        self.p.delete_line([l["id"] for l in self.p.state()["lines"] if l["text"] == "world"][0])
        self.assertEqual(touched(), {a: True, b: True})
        self.p.replace_lines(a, [seg(0, "fresh")])
        self.assertEqual(touched(), {a: False, b: True})

    def test_run_record_is_cleared_with_the_last_line(self):
        a, _ = self.two()
        self.p.replace_lines(a, [seg(0, "only")], run={"model": "m", "language": "th", "at": 1.0})
        self.p.delete_line(next(l["id"] for l in self.p.state()["lines"] if l["spk"] == a))
        self.assertNotIn("run", Project(self.dir).speaker(a))

    def test_missed_speech_is_voice_no_line_covers_for_two_seconds_or_more(self):
        a, b = self.two()
        speech = [[0, 10], [20, 21], [30, 40], [50, 53], [60, 64]]
        self.p.replace_lines(a, [seg(0, "x"), seg(5, "y"), seg(31, "z"), seg(51.5, "w"), {"start": 58, "end": 61, "text": "v"}],
                             speech=speech)
        missed = lambda sid: next(s["missed"] for s in Project(self.dir).state()["speakers"] if s["id"] == sid)
        self.assertEqual(missed(a), [{"start": 1, "end": 5}, {"start": 6, "end": 10}, {"start": 32, "end": 40},
                                     {"start": 61, "end": 64}])
        self.assertEqual(missed(b), [])

    def test_dismissed_missed_speech_stays_gone_until_the_next_full_run(self):
        a, _ = self.two()
        self.p.replace_lines(a, [seg(0, "x")], speech=[[0, 30]])
        missed = lambda: next(s["missed"] for s in Project(self.dir).state()["speakers"] if s["id"] == a)
        self.assertEqual(missed(), [{"start": 1, "end": 30}])
        self.p.dismiss_missed(a, 1.001, 29.999)
        self.assertEqual(missed(), [])
        self.p.replace_lines(a, [seg(0, "x")])
        self.assertEqual(missed(), [{"start": 1, "end": 30}])

    def test_dismissing_one_missed_stretch_keeps_the_others(self):
        a, _ = self.two()
        self.p.replace_lines(a, [seg(0, "x"), seg(5, "y")], speech=[[0, 30]])
        self.p.dismiss_missed(a, 6, 30)
        self.assertEqual(self.p.state()["speakers"][0]["missed"], [{"start": 1, "end": 5}])
        self.p.dismiss_missed("nope", 1, 5)

    def test_add_line_at_covers_the_missed_stretch(self):
        a, b = self.two()
        self.p.replace_lines(a, [seg(0, "x")], speech=[[0, 30]])
        line = self.p.add_line_at(a, 1, 30)
        self.assertEqual((line["spk"], line["start"], line["end"], line["text"], line["orig"]), (a, 1, 30, "", ""))
        st = Project(self.dir).state()
        self.assertIn(line["id"], [l["id"] for l in st["lines"]])
        self.assertEqual(st["speakers"][0]["missed"], [])
        self.assertIsNone(self.p.add_line_at("nope", 1, 5))
        self.assertIsNone(self.p.add_line_at(b, 5, 5))

    def test_speaker_without_speech_has_no_missed_speech_and_exports_ignore_it(self):
        a, b = self.two()
        before = [self.p.export(k) for k in ("txt", "srt", "json")]
        self.assertEqual([s["missed"] for s in self.p.state()["speakers"]], [[], []])
        self.p.replace_lines(a, [seg(0, "hello"), seg(5, "world")], speech=[[0, 30]])
        self.assertEqual(self.p.state()["speakers"][0]["missed"], [{"start": 1, "end": 5}, {"start": 6, "end": 30}])
        self.assertEqual([self.p.export(k) for k in ("txt", "srt", "json")], before)
        self.p.replace_lines(a, [seg(0, "again")])
        self.assertEqual(self.p.speaker(a)["speech"], [[0, 30]])

    def test_every_line_carries_its_review_flags(self):
        upload(self.p, "1-a.wav", wav())
        sid = self.p.state()["speakers"][0]["id"]
        self.p.replace_lines(sid, [seg(0, "สวัสดีครับ"), seg(1, "ฟังไม่ชัด", conf=-1.2), {**seg(2, "อีเขียบ อีเขียบ อีเขียบ"), "suspect": True},
                                   seg(3, "Essential Principal เลยนะเว้ย"), seg(4, "OK นะ"), seg(5, "แก้ทีหลัง")])
        ids = {l["text"]: l["id"] for l in self.p.state()["lines"]}
        self.p.edit_lines([{"id": ids["อีเขียบ อีเขียบ อีเขียบ"], "text": "อีกแล้ว"}, {"id": ids["แก้ทีหลัง"], "text": "แก้แล้ว"}])
        added = self.p.add_line_after(ids["แก้ทีหลัง"])["id"]
        self.p.edit_lines([{"id": added, "text": "พิมพ์เอง"}])
        self.p.add_line_after(added)
        flags = {l["text"]: (l["unsure"], l["mixed"], l["edited"]) for l in Project(self.dir).state()["lines"]}
        self.assertEqual(flags, {"สวัสดีครับ": (False, False, False), "ฟังไม่ชัด": (False, False, False),
                                 "อีกแล้ว": (False, False, True), "Essential Principal เลยนะเว้ย": (False, True, False),
                                 "OK นะ": (False, True, False), "แก้แล้ว": (False, False, True),
                                 "พิมพ์เอง": (False, False, True), "": (False, False, False)})

    def test_old_lines_without_new_fields_get_flags(self):
        self.dir.mkdir()
        (self.dir / "project.json").write_text(json.dumps({
            "speakers": [{"id": "s1", "name": "Old", "file": "s1.flac", "ext": ".flac", "duration": None, "source": "1-Old.flac"}],
            "lines": [{"id": "l2", "spk": "s1", "start": 1.0, "end": 2.0, "text": "hi there", "conf": -1.5, "ok": False}],
            "seq": 2}))
        line = Project(self.dir).state()["lines"][0]
        self.assertEqual((line["unsure"], line["mixed"], line["edited"]), (False, False, False))

    def lined(self, text, words, **kw):
        upload(self.p, "1-a.wav", wav())
        sid = self.p.state()["speakers"][0]["id"]
        self.p.replace_lines(sid, [{**seg(0, text, **kw), "words": words}])
        return Project(self.dir).state()["lines"][0]

    def saved(self, *lines):
        upload(self.p, "1-a.wav", wav())
        sid = self.p.state()["speakers"][0]["id"]
        self.p.replace_lines(sid, [{"start": i * 10.0, "end": i * 10.0 + kw.pop("length", 5.0), "text": text, "conf": kw.pop("conf", -0.1), **kw}
                                   for i, (text, kw) in enumerate(lines)])
        return {l["text"]: l for l in Project(self.dir).state()["lines"]}

    def test_each_cause_gives_its_own_reason(self):
        got = self.saved(("fine words", dict(length=2.0, words=[pw(" fine"), pw(" words", 0.1)])),
                         ("อีเขียบ" * 4, dict(suspect=True)),
                         ("สวัสดี こんにちは", dict(suspect=True)),
                         ("สวัสดีครับผมชื่อสมชายยินดีที่ได้รู้จัก", dict(suspect=True, length=1.0)),
                         ("old", dict(suspect=True, length=2.0)),
                         ("fine", dict(length=2.0)))
        self.assertEqual({t: (l["reasons"], l["unsure"]) for t, l in got.items()},
                         {"fine words": (["unsure word"], True), "อีเขียบ" * 4: (["repeated phrase"], True),
                          "สวัสดี こんにちは": (["foreign letters"], True), "สวัสดีครับผมชื่อสมชายยินดีที่ได้รู้จัก": (["timing"], True),
                          "old": (["looks made up"], True), "fine": ([], False)})

    def test_several_reasons_come_in_the_stated_order(self):
        text = "x こんにちは" + "ก" * 40
        got = self.saved((text, dict(suspect=True, length=1.0, words=[pw("x", 0.1), pw(" " + text[2:])])))
        self.assertEqual(got[text]["reasons"], ["unsure word", "repeated phrase", "foreign letters", "timing"])

    def test_long_line_with_far_too_little_text_is_missed_speech(self):
        got = self.saved(("าง", dict(length=14.0)), ("นี้", dict(length=9.0)),
                         ("a perfectly normal line of speech", dict(length=14.0)),
                         ("เพ", dict(length=3.9)), ("เพ ", dict(length=4.0)))
        self.assertEqual({t: l["reasons"] for t, l in got.items()},
                         {"าง": ["missed speech"], "นี้": ["missed speech"], "a perfectly normal line of speech": [],
                          "เพ": [], "เพ ": ["missed speech"]})
        self.assertTrue(got["าง"]["unsure"])

    def test_missed_speech_comes_after_the_other_reasons_and_editing_clears_it(self):
        got = self.saved(("x", dict(suspect=True, length=10.0, words=[pw("x", 0.1)])), ("าง", dict(length=14.0)))
        self.assertEqual(got["x"]["reasons"], ["unsure word", "looks made up", "missed speech"])
        self.p.edit_lines([{"id": l["id"], "text": t + " แก้"} for t, l in got.items()])
        self.assertEqual([l["reasons"] for l in self.p.state()["lines"]], [[], []])

    def test_editing_clears_unsure_reasons_and_underlines(self):
        got = self.saved(("a b", dict(words=[pw(" a", 0.1), pw(" b")])), ("こんにちは", dict(suspect=True)), ("hello", dict(conf=-1.2)))
        self.p.edit_lines([{"id": l["id"], "text": t + " แก้"} for t, l in got.items()])
        for l in Project(self.dir).state()["lines"]:
            self.assertEqual((l["unsure"], l["reasons"], l["unsure_words"]), (False, [], []), l["text"])

    def test_lines_typed_by_hand_are_never_unsure(self):
        got = self.saved(("first", dict()))
        new = self.p.add_line_after(got["first"]["id"])["id"]
        self.p.edit_lines([{"id": new, "text": "こんにちは " + "ก" * 40}])
        line = next(l for l in Project(self.dir).state()["lines"] if l["id"] == new)
        self.assertEqual((line["unsure"], line["reasons"], line["unsure_words"]), (False, [], []))

    def test_line_with_a_word_under_the_cutoff_is_unsure_and_spans_that_word(self):
        line = self.lined("hello wrold again", [pw(" hello"), pw(" wrold", 0.2), pw(" again")])
        self.assertTrue(line["unsure"])
        self.assertEqual([line["text"][s:e] for s, e in line["unsure_words"]], ["wrold"])

    def test_spans_follow_repeated_words_in_order(self):
        line = self.lined("no no no", [pw(" no"), pw(" no", 0.1), pw(" no", 0.1)])
        self.assertEqual(line["unsure_words"], [[3, 5], [6, 8]])

    def test_touching_thai_pieces_make_one_unsure_word(self):
        line = self.lined("โดนดองครีม", [pw("โดน"), pw("ดอง", 0.25), pw("ครีม", 0.2)])
        self.assertEqual([line["text"][s:e] for s, e in line["unsure_words"]], ["ดองครีม"])

    def test_confident_words_are_not_unsure_whatever_the_line_confidence(self):
        line = self.lined("hello world", [pw(" hello"), pw(" world", 0.5)], conf=-2.0)
        self.assertEqual((line["unsure"], line["unsure_words"]), (False, []))

    def test_editing_the_text_clears_the_unsure_words(self):
        line = self.lined("hello wrold", [pw(" hello"), pw(" wrold", 0.2)])
        self.p.edit_lines([{"id": line["id"], "text": "hello world"}])
        line = self.p.state()["lines"][0]
        self.assertEqual((line["unsure"], line["unsure_words"]), (False, []))

    def test_words_are_stored_rounded_and_stay_out_of_exports(self):
        line = self.lined("hello", [pw(" hello", 0.123456)])
        self.assertEqual(line["words"], [pw(" hello", 0.123)])
        self.assertNotIn("words", self.p.export("json")[0])
        self.assertNotIn("0.123", self.p.export("txt")[0] + self.p.export("srt")[0])

    def test_reset_keeps_unrelated_files(self):
        self.two()
        (self.dir / "keep.txt").write_text("mine")
        self.p.reset()
        self.assertEqual(self.p.state(), {"speakers": [], "lines": []})
        self.assertTrue((self.dir / "keep.txt").exists())
        self.assertFalse((self.dir / "audio").exists() or (self.dir / "project.json").exists())

    def test_export(self):
        a, b = self.two()
        self.p.rename_speaker(a, "Alice")
        txt, ctype = self.p.export("txt")
        self.assertEqual(txt, "[00:00] Alice: hello\n[00:02] b: other\n[00:05] Alice: world\n")
        self.assertIn("00:00:00,000 --> 00:00:01,000", self.p.export("srt")[0])
        self.assertEqual(json.loads(self.p.export("json")[0])[1]["speaker"], "b")

    def test_loads_existing_project_json(self):
        self.dir.mkdir()
        (self.dir / "project.json").write_text(json.dumps({
            "speakers": [{"id": "s1", "name": "Old", "file": "s1.flac", "ext": ".flac", "duration": None, "source": "1-Old.flac"}],
            "lines": [{"id": "l2", "spk": "s1", "start": 1.5, "end": 2.0, "text": "hi", "orig": "hi", "conf": -0.2, "ok": True}],
            "seq": 2}))
        q = Project(self.dir)
        self.assertEqual(q.export("txt")[0], "[00:01] Old: hi\n")
        self.assertEqual(q.add_line_after("l2")["id"], "l3")
        (self.dir / "project.json").write_text("{broken")
        self.assertEqual(Project(self.dir).state()["lines"], [])


class HallucinationRuleTest(unittest.TestCase):
    def test_flags_repeats_and_foreign_scripts(self):
        for text in ["แก ร ั ติ เลย อี เข ีย บ อี เข ีย บ อี เข ีย บ อี เข ีย บ ไม่ ทัน พอ เล่น", "อีเขียบ อีเขียบ อีเขียบ อีเขียบ",
                     "กี่หน้ากี่หน้ากี่หน้ากี่หน้า",
                     "además habíaон", "складดิงตรงนี้", "เออ ตอนนี้一點ก็เดี๋ยว", "Mike is cursing too, Γειά"]:
            self.assertTrue(looks_hallucinated(text), text)

    def test_keeps_normal_thai_english_and_mixed(self):
        for text in ["เรียนแพทย์ดีกว่า", "No Way", "KMIT Open Courtware", "Essential Principal เลยนะเว้ย",
                     "อ่า ฮ่า ฮ่า ฮ่า", "เล่นๆ ตอนข้าง ตรงชีพหว่ะ", "เสียไป ๆ บางเมื่อ ๆ ๆ เยอะ ๆ", "เล่มละพัน 1,000 บาท?",
                     "Sami in år 2000", "Tiếng Việt", "นะนะนะนะนะ", "ไม่ไม่ไม่ไม่", "ฮ่าฮ่าฮ่าฮ่า", "ha ha ha ha",
                     "555555555", "1000000000", "กี่หน้ากี่หน้ากี่หน้า", "อีเขียบ อีเขียบ อีเขียบ"]:
            self.assertFalse(looks_hallucinated(text), text)


def w(text, start, end, prob=0.9):
    return {"text": text, "start": start, "end": end, "prob": prob}


def lines(*segments):
    return [(l["text"], round(l["start"], 2), round(l["end"], 2)) for l in lines_from_segments(segments)]


def full_lines(*segments):
    return list(lines_from_segments(segments))


def pw(text, prob=0.9):
    return {"text": text, "prob": prob}


class LinesFromSegmentsTest(unittest.TestCase):
    def test_whole_segment_line_carries_all_its_words(self):
        words = [w(" hello", 0.0, 0.4, 0.2), w(" world", 0.4, 0.8)]
        self.assertEqual(full_lines({**seg(0, " hello world"), "words": words})[0]["words"], [pw(" hello", 0.2), pw(" world")])

    def test_segment_without_words_gives_empty_words(self):
        self.assertEqual(full_lines(seg(0, "hello"))[0]["words"], [])

    def test_split_line_carries_only_its_own_words(self):
        words = [w(" one", 0.0, 0.3), w(" two", 0.3, 0.6, 0.1), w(" three", 5.0, 5.3), w(" four", 5.3, 5.6)]
        got = full_lines({**seg(0, "one two three four"), "end": 5.6, "words": words})
        self.assertEqual([(l["text"], l["words"]) for l in got],
                         [("one two", [pw(" one"), pw(" two", 0.1)]), ("three four", [pw(" three"), pw(" four")])])

    def test_joined_fragments_carry_all_parts_words_in_order(self):
        piece = lambda t, a: {**seg(a, t), "end": a + 0.1, "words": [w(t, a, a + 0.1, 0.4)]}
        got = full_lines(piece("ก", 0.0), piece("็คือ", 0.1))
        self.assertEqual([(l["text"], l["words"]) for l in got], [("ก็คือ", [pw("ก", 0.4), pw("็คือ", 0.4)])])

    def test_segment_without_words_is_one_line_and_filters_still_apply(self):
        self.assertEqual(lines(seg(0, " hello "), seg(1, "  "), seg(2, "noise", conf=-1.5, no_speech=0.9), seg(3, "world")),
                         [("hello", 0, 1), ("world", 3, 4)])

    def test_thai_pause_moves_the_stray_piece_to_the_next_line(self):
        words = [w(" ผม", 0.0, 0.3), w("เรียน", 0.3, 0.8), w(" อย", 0.8, 0.9), w("าก", 5.4, 5.6), w("เรียน", 5.6, 6.0)]
        self.assertEqual(lines({**seg(0, "ผมเรียน อยากเรียน"), "end": 6.0, "words": words}),
                         [("ผมเรียน", 0.0, 0.8), ("อยากเรียน", 5.4, 6.0)])

    def test_no_word_start_nearby_cuts_at_the_pause(self):
        words = [w("ก", 0.0, 0.2), w("าร", 0.2, 0.4), w("บ", 2.5, 2.7), w("ัญชี", 2.7, 3.0)]
        self.assertEqual(lines({**seg(0, "การบัญชี"), "end": 3.0, "words": words}),
                         [("การ", 0.0, 0.4), ("บัญชี", 2.5, 3.0)])

    def test_fallback_cut_never_splits_a_thai_syllable(self):
        dependent = [w("เล่น", 0.0, 0.4), w("ก", 0.4, 0.5), w("าร", 3.0, 3.2), w("บ้าน", 3.2, 3.5)]
        self.assertEqual(lines({**seg(0, "เล่นการบ้าน"), "end": 3.5, "words": dependent}),
                         [("เล่น", 0.0, 0.4), ("การบ้าน", 3.0, 3.5)])
        leading = [w("ดี", 0.0, 0.3), w("โ", 0.3, 0.4), w("อ", 2.0, 2.1), w("เค", 2.1, 2.3)]
        self.assertEqual(lines({**seg(0, "ดีโอเค"), "end": 2.3, "words": leading}),
                         [("ดี", 0.0, 0.3), ("โอเค", 2.0, 2.3)])

    def test_syllable_piece_between_two_pauses_joins_the_next_line(self):
        words = [w("ดี", 0.0, 0.3), w("ก", 1.0, 1.1), w("าร", 2.0, 2.2), w(" ม", 2.2, 2.3), w("า", 4.0, 4.2)]
        self.assertEqual(lines({**seg(0, "ดีการ มา"), "end": 4.2, "words": words}),
                         [("ดี", 0.0, 0.3), ("การ", 2.0, 2.2), ("มา", 4.0, 4.2)])

    def test_english_after_thai_counts_as_a_word_start(self):
        words = [w("โหลด", 0.0, 0.4), w("ห", 0.4, 0.5), w("KM", 0.5, 0.6), w("IT", 1.4, 1.6)]
        self.assertEqual(lines({**seg(0, "โหลดหKMIT"), "end": 1.6, "words": words}),
                         [("โหลดห", 0.0, 0.5), ("KMIT", 1.4, 1.6)])

    def test_run_of_one_piece_segments_joins_into_one_line_with_the_next(self):
        piece = lambda t, a: {**seg(a, t), "end": a + 0.1}
        self.assertEqual(lines(piece(" ม", 0.0), piece("ั", 0.1), piece("น", 0.2), piece("ก", 0.3), piece("็", 0.4),
                               {**seg(0.5, "จะไปเลย"), "end": 2.0}),
                         [("มันก็จะไปเลย", 0.0, 2.0)])

    def test_line_cut_inside_a_word_joins_the_next_even_after_a_pause(self):
        self.assertEqual(lines(seg(0, "ก"), seg(3, "็คือแบบว่า"), seg(8, "โ"), seg(12, "อเค")),
                         [("ก็คือแบบว่า", 0, 4), ("โอเค", 8, 13)])

    def test_tiny_lines_far_apart_stay_separate(self):
        self.assertEqual(lines(seg(0, "ใช่"), seg(5, "ครับ")), [("ใช่", 0, 1), ("ครับ", 5, 6)])

    def test_joined_run_stays_within_twelve_seconds(self):
        out = lines(*[{**seg(i * 0.5, "ก"), "end": i * 0.5 + 0.5} for i in range(30)])
        self.assertGreater(len(out), 1)
        self.assertTrue(all(end - start <= 12 for _, start, end in out))
        self.assertEqual("".join(t for t, _, _ in out), "ก" * 30)

    def test_joined_english_pieces_keep_a_space(self):
        piece = lambda t, a: {**seg(a, t), "end": a + 0.1}
        self.assertEqual(lines(piece("go", 0.0), piece("to", 0.1), {**seg(0.2, "bed"), "end": 1.0}), [("go to bed", 0.0, 1.0)])

    def test_short_pauses_do_not_split(self):
        words = [w(" ก็", 0.0, 0.3), w(" จริง", 0.8, 1.2)]
        self.assertEqual(lines({**seg(0, "ก็ จริง"), "end": 1.2, "words": words}), [("ก็ จริง", 0.0, 1.2)])

    def test_line_over_twelve_seconds_splits_at_its_biggest_pause(self):
        words = [w(f" w{i}", i * 0.55, i * 0.55 + 0.5) for i in range(15)]
        words += [w(f" w{i}", 8.6 + (i - 15) * 0.55, 8.6 + (i - 15) * 0.55 + 0.5) for i in range(15, 30)]
        out = lines({**seg(0, "x"), "end": 16.8, "words": words})
        self.assertEqual([(t.split()[0], t.split()[-1], a, b) for t, a, b in out],
                         [("w0", "w14", 0.0, 8.2), ("w15", "w29", 8.6, 16.8)])

    def test_impossibly_fast_line_is_flagged_not_dropped(self):
        out = list(lines_from_segments([{**seg(57.2, "สินค้า คงเหลือ สิบเอ็ด บาท"), "end": 57.8},
                                        {**seg(60.0, "เออ แพงจังอะ"), "end": 61.0}]))
        self.assertEqual([(l["text"], l["suspect"]) for l in out],
                         [("สินค้า คงเหลือ สิบเอ็ด บาท", True), ("เออ แพงจังอะ", False)])

    def test_repeat_needs_four_in_a_row_and_short_lines_are_never_too_fast(self):
        out = list(lines_from_segments([{**seg(0, "กี่หน้ากี่หน้ากี่หน้า"), "end": 3.0}, {**seg(3, "กี่หน้ากี่หน้ากี่หน้ากี่หน้า"), "end": 6.0},
                                        {**seg(6, "ขอบคุณครับ"), "end": 6.1}, {**seg(7, "ขอบคุณครับขอบคุณครับ"), "end": 7.5},
                                        {**seg(9, "สวัสดีครับ ผมชื่อสมชาย"), "end": 9.5}, {**seg(10, "Gamma Γειά"), "end": 12.0}]))
        self.assertEqual([l["suspect"] for l in out], [False, True, False, True, True, True])

    def test_split_lines_get_their_own_confidence(self):
        words = [w(" ดี", 0.0, 0.4, 0.9), w(" มาก", 0.4, 0.8, 0.9), w(" xq", 3.0, 3.4, 0.05)]
        out = list(lines_from_segments([{**seg(0, "ดี มาก xq", conf=-0.5), "end": 3.4, "words": words}]))
        self.assertEqual([l["text"] for l in out], ["ดี มาก", "xq"])
        self.assertAlmostEqual(out[0]["conf"], -0.105, places=3)
        self.assertAlmostEqual(out[1]["conf"], -2.996, places=3)

    def test_unsplit_line_keeps_the_segment_confidence(self):
        words = [w(" ดี", 0.0, 0.4, 0.1), w(" มาก", 0.5, 0.8, 0.1)]
        out = list(lines_from_segments([{**seg(0, "ดี มาก", conf=-0.5), "end": 0.8, "words": words}]))
        self.assertEqual(out[0]["conf"], -0.5)


class ModelCatalogTest(unittest.TestCase):
    def test_lists_every_model_with_thai_model_states(self):
        with tempfile.TemporaryDirectory() as d:
            (Path(d) / "models" / "pathumma").mkdir(parents=True)
            (Path(d) / "models" / "pathumma" / "model.bin").write_bytes(b"")
            (Path(d) / "models" / "typhoon").mkdir(parents=True)
            for f in MODEL_FILES:
                (Path(d) / "models" / "typhoon" / f).write_bytes(b"")
            catalog = {m["name"]: m for m in model_catalog(d)}
        self.assertEqual(list(catalog)[:4], ["small", "medium", "large-v3-turbo", "large-v3"])
        self.assertEqual({n: (m["thai"], m.get("state")) for n, m in catalog.items() if m["thai"]},
                         {"typhoon": (True, "installed"), "pathumma": (True, "incomplete")})
        self.assertNotIn("state", catalog["large-v3"])
        self.assertEqual({n for n, m in catalog.items() if m["slow"]}, {"medium", "large-v3-turbo", "large-v3", "typhoon", "pathumma"})
        self.assertEqual({m["default"]: n for n, m in catalog.items() if m.get("default")}, {"cpu": "small", "gpu": "large-v3"})
        self.assertTrue(all(m["label"] for m in catalog.values()))

    def test_missing_thai_model(self):
        with tempfile.TemporaryDirectory() as d:
            self.assertEqual({m["name"]: m.get("state") for m in model_catalog(d) if m["thai"]},
                             {"typhoon": "missing", "pathumma": "missing"})


class WhisperEngineTest(unittest.TestCase):
    def test_segments_carry_word_timings(self):
        word = type("W", (), {"start": 0.0, "end": 0.5, "word": " hi", "probability": 0.9})
        segment = type("S", (), {"start": 0.0, "end": 1.0, "text": " hi", "avg_logprob": -0.2, "no_speech_prob": 0.1,
                                 "words": [word]})

        class Model:
            def transcribe(self, audio, **kw):
                return iter([segment]), type("Info", (), {"language": "th"})

        class Engine(WhisperEngine):
            load_audio = staticmethod(lambda path: [0.0] * 32000)

            def _load(self, prefer_cpu):
                self._model, self.device = Model(), "cpu"
        engine = Engine("m", True, lambda **kw: None)
        dur, segs = engine.transcribe("a.wav", "th", "")
        self.assertEqual((dur, engine.language), (2.0, "th"))
        self.assertEqual(list(segs)[0]["words"], [{"start": 0.0, "end": 0.5, "text": " hi", "prob": 0.9}])


    def test_voice_lists_seconds_with_voice(self):
        vad = types.ModuleType("faster_whisper.vad")
        vad.VadOptions = lambda **kw: kw
        vad.get_speech_timestamps = lambda audio, opts: ([{"start": 16000, "end": 40000}] if opts == {"min_silence_duration_ms": 500} else [])

        class Engine(WhisperEngine):
            load_audio = staticmethod(lambda path: [0.0] * 48000)

            def _load(self, prefer_cpu):
                pass
        with mock.patch.dict(sys.modules, {"faster_whisper": types.ModuleType("faster_whisper"), "faster_whisper.vad": vad}):
            self.assertEqual(Engine("m", True, lambda **kw: None).voice("a.wav"), [[1.0, 2.5]])


class ChildEngine:
    """Runs inside the child process of ProcessEngine; some model names crash it the way a CUDA abort does."""
    available = staticmethod(lambda: True)

    def __init__(self, model_name, prefer_cpu, on_status):
        if model_name == "crash-on-load" and not prefer_cpu:
            os._exit(134)
        self.model_name, self.device, self.language = model_name, "cpu" if prefer_cpu else "cuda", ""
        on_status(message=f"loaded on {self.device}")

    def transcribe(self, path, language, prompt):
        if self.model_name == "crash-always":
            os._exit(134)
        if self.model_name == "crash-once" and not os.path.exists(path + ".crashed"):
            open(path + ".crashed", "w").close()
            os._exit(134)
        self.language = language or "th"

        def gen():
            for i in range(40 if self.model_name == "slow" else 2):
                if self.model_name == "crash-mid-run" and self.device == "cuda" and i == 1:
                    os._exit(134)
                if self.model_name == "slow":
                    time.sleep(0.05)
                yield {**seg(i, f"{self.device} {os.getpid()} line {i}"), "words": []}
        return 4.0, gen()

    def voice(self, path):
        if self.model_name == "crash-in-voice":
            os._exit(134)
        if self.model_name == "bad-voice":
            raise ValueError("no vad")
        return [[0.0, 1.5]]


class IsolatedEngine(ProcessEngine):
    INNER = ChildEngine


class ProcessEngineTest(unittest.TestCase):
    def test_runs_in_a_child_process_and_streams_segments(self):
        notes = []
        engine = IsolatedEngine("ok", False, lambda **kw: notes.append(kw))
        dur, segs = engine.transcribe("a.wav", None, "")
        texts = [s["text"] for s in segs]
        self.assertEqual((dur, engine.device, engine.language, len(texts)), (4.0, "cuda", "th", 2))
        self.assertNotEqual(texts[0].split()[1], str(os.getpid()))
        self.assertIn({"message": "loaded on cuda"}, notes)

    def test_voice_goes_over_the_pipe_and_errors_and_crashes_come_back(self):
        engine = IsolatedEngine("ok", True, lambda **kw: None)
        self.assertEqual(engine.voice("a.wav"), [[0.0, 1.5]])
        self.assertEqual(next(engine.transcribe("a.wav", "th", "")[1])["text"].split()[2:], ["line", "0"])
        with self.assertRaisesRegex(RuntimeError, "no vad"):
            IsolatedEngine("bad-voice", True, lambda **kw: None).voice("a.wav")
        with self.assertRaises(EngineCrashed):
            IsolatedEngine("crash-in-voice", True, lambda **kw: None).voice("a.wav")

    def test_crash_while_loading_on_the_gpu_retries_on_the_processor(self):
        notes = []
        engine = IsolatedEngine("crash-on-load", False, lambda **kw: notes.append(kw))
        self.assertEqual(engine.device, "cpu")
        self.assertTrue(any("graphics card" in n.get("note", "") for n in notes))

    def test_cancel_stops_the_child_and_the_same_process_serves_the_next_run(self):
        engine = IsolatedEngine("slow", True, lambda **kw: None)
        segs = engine.transcribe("a.wav", "th", "")[1]
        first = next(segs)["text"]
        t = time.time()
        segs.close()
        self.assertLess(time.time() - t, 1.0)
        again = next(engine.transcribe("a.wav", "th", "")[1])["text"]
        self.assertEqual((first.split()[1], again.split()[2:]), (again.split()[1], ["line", "0"]))

    def test_closing_before_reading_still_leaves_the_pipe_clean(self):
        engine = IsolatedEngine("slow", True, lambda **kw: None)
        engine.transcribe("a.wav", "th", "")[1].close()
        self.assertEqual(next(engine.transcribe("a.wav", "th", "")[1])["text"].split()[2:], ["line", "0"])


class FakeEngine:
    segments = [seg(0, " hello "), seg(1, ""), seg(2, "noise", conf=-1.5, no_speech=0.9), seg(3, "world")]
    speech = [[0.0, 3.5]]
    job = None

    def __init__(self, model_name, prefer_cpu, on_status):
        self.device = "cpu"

    @staticmethod
    def available():
        return True

    def transcribe(self, path, language, prompt):
        return 4.0, iter(self.segments)

    def voice(self, path):
        return self.speech


class JobTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.p = Project(Path(self.tmp.name))
        upload(self.p, "1-a.wav", wav())
        self.sid = self.p.state()["speakers"][0]["id"]
        self.p.replace_lines(self.sid, [seg(0, "old")])

    def run_job(self, engine_cls, **opts):
        job = Job(self.p, engine_cls)
        FakeEngine.job = job
        self.assertEqual(job.start({"speakers": [self.sid], "model": "m", **opts}), {"ok": True})
        job._thread.join(10)
        return job

    def test_success_replaces_lines_and_filters(self):
        job = self.run_job(FakeEngine)
        st = job.status()
        self.assertEqual((st["phase"], st["running"], st["device"]), ("done", False, "cpu"))
        self.assertEqual(st["recent"], ["a [00:00] hello", "a [00:03] world"])
        self.assertNotIn("t0", st)
        self.assertEqual([t for _, t in texts(self.p)], ["hello", "world"])
        self.assertEqual(self.p.speaker(self.sid)["duration"], 4.0)

    def test_success_stores_the_voice_stretches(self):
        self.run_job(FakeEngine)
        self.assertEqual(Project(self.p.dir).speaker(self.sid)["speech"], [[0.0, 3.5]])
        self.assertEqual(self.p.state()["speakers"][0]["missed"], [{"start": 1.0, "end": 3.0}])

    def test_failed_or_cancelled_run_keeps_previous_voice(self):
        self.run_job(FakeEngine)

        class Boom(FakeEngine):
            speech = [[9.0, 10.0]]

            def transcribe(self, path, language, prompt):
                raise RuntimeError("boom")

        class Cancelling(Boom):
            def transcribe(self, path, language, prompt):
                FakeEngine.job.cancel()
                return FakeEngine.transcribe(self, path, language, prompt)
        for engine_cls in (Boom, Cancelling):
            self.run_job(engine_cls)
            self.assertEqual(self.p.speaker(self.sid)["speech"], [[0.0, 3.5]])
            self.assertEqual([t for _, t in texts(self.p)], ["hello", "world"])

    def test_voice_failure_still_saves_the_lines(self):
        class NoVad(FakeEngine):
            def voice(self, path):
                raise RuntimeError("vad broke")
        st = self.run_job(NoVad).status()
        self.assertEqual(st["phase"], "done")
        self.assertIn("vad broke", st["note"])
        self.assertEqual([t for _, t in texts(self.p)], ["hello", "world"])
        self.assertNotIn("speech", self.p.speaker(self.sid))

    def test_voice_goes_through_the_child_process(self):
        self.run_job(IsolatedEngine, device="cpu")
        self.assertEqual(self.p.speaker(self.sid)["speech"], [[0.0, 1.5]])

    def test_crash_while_finding_voice_ends_the_run_and_keeps_old_lines(self):
        st = self.run_job(IsolatedEngine, model="crash-in-voice", device="cpu").status()
        self.assertEqual(st["phase"], "error")
        self.assertIn("stopped unexpectedly", st["error"])
        self.assertEqual([t for _, t in texts(self.p)], ["old"])

    def test_words_reach_the_state(self):
        class Worded(FakeEngine):
            segments = [{**seg(0, "hello"), "words": [w("hello", 0.0, 0.5, 0.2)]}]
        self.run_job(Worded)
        self.assertEqual(self.p.state()["lines"][0]["words"], [pw("hello", 0.2)])

    def test_success_records_the_run_options(self):
        self.run_job(FakeEngine, language="th", prompt=" ขนุน, Go Fiber ")
        run = Project(self.p.dir).speaker(self.sid)["run"]
        self.assertEqual({k: run[k] for k in ("model", "language", "vocabulary", "device")},
                         {"model": "m", "language": "th", "vocabulary": "ขนุน, Go Fiber", "device": "cpu"})
        self.assertGreater(run["at"], 0)

    def test_status_reports_audio_already_done_by_earlier_speakers(self):
        upload(self.p, "2-b.wav", wav())
        ids = [s["id"] for s in self.p.state()["speakers"]]
        seen = []

        class Watching(FakeEngine):
            def transcribe(self, path, language, prompt):
                seen.append(FakeEngine.job.status()["audio_done"])
                return super().transcribe(path, language, prompt)
        job = Job(self.p, Watching)
        FakeEngine.job = job
        self.assertEqual(job.start({"speakers": ids, "model": "m"}), {"ok": True})
        job._thread.join(10)
        self.assertEqual(seen, [0.0, 4.0])

    def test_vocabulary_reaches_engine(self):
        got = []

        class Listening(FakeEngine):
            def transcribe(self, path, language, prompt):
                got.append((language, prompt))
                return super().transcribe(path, language, prompt)
        self.run_job(Listening, language="th", prompt="  ขนุน, Go Fiber ")
        self.assertEqual(got, [("th", "ขนุน, Go Fiber")])

    def test_hallucinated_lines_are_kept_and_flagged(self):
        class Noisy(FakeEngine):
            segments = [seg(0, "สวัสดี"), seg(1, "อีเขียบ อีเขียบ อีเขียบ อีเขียบ"), seg(2, "además habíaон")]
        self.run_job(Noisy)
        lines = Project(self.p.dir).state()["lines"]
        self.assertEqual([(l["text"], l["suspect"]) for l in lines],
                         [("สวัสดี", False), ("อีเขียบ อีเขียบ อีเขียบ อีเขียบ", True), ("además habíaон", True)])

    def test_failed_or_cancelled_run_keeps_previous_record(self):
        self.run_job(FakeEngine, language="th")
        before = self.p.speaker(self.sid)["run"]

        class Boom(FakeEngine):
            def transcribe(self, path, language, prompt):
                raise RuntimeError("boom")

        class Cancelling(FakeEngine):
            def transcribe(self, path, language, prompt):
                FakeEngine.job.cancel()
                return super().transcribe(path, language, prompt)
        for engine_cls in (Boom, Cancelling):
            self.run_job(engine_cls, language="en")
            self.assertEqual(self.p.speaker(self.sid)["run"], before)

    def test_failure_keeps_old_lines(self):
        class Boom(FakeEngine):
            def transcribe(self, path, language, prompt):
                def gen():
                    yield seg(0, "partial")
                    raise RuntimeError("boom")
                return 4.0, gen()
        st = self.run_job(Boom).status()
        self.assertEqual(st["phase"], "error")
        self.assertIn("boom", st["error"])
        self.assertEqual([t for _, t in texts(self.p)], ["old"])
        self.assertNotIn("run", self.p.speaker(self.sid))

    def test_cancel_keeps_old_lines(self):
        class Cancelling(FakeEngine):
            def transcribe(self, path, language, prompt):
                def gen():
                    yield seg(0, "first")
                    FakeEngine.job.cancel()
                    yield seg(1, "second")
                return 4.0, gen()
        st = self.run_job(Cancelling).status()
        self.assertEqual(st["phase"], "cancelled")
        self.assertEqual([t for _, t in texts(self.p)], ["old"])

    def test_cuda_failure_falls_back_to_cpu(self):
        class Cuda(FakeEngine):
            def __init__(self, *a):
                self.device = "cuda"

            def use_cpu(self):
                self.device = "cpu"

            def transcribe(self, path, language, prompt):
                if self.device == "cuda":
                    raise RuntimeError("cuda died")
                return super().transcribe(path, language, prompt)
        st = self.run_job(Cuda).status()
        self.assertEqual((st["phase"], st["device"]), ("done", "cpu"))
        self.assertIn("cuda died", st["note"])
        self.assertEqual([t for _, t in texts(self.p)], ["hello", "world"])

    def test_crash_mid_run_on_the_gpu_finishes_on_the_processor(self):
        job = self.run_job(IsolatedEngine, model="crash-mid-run")
        st = job.status()
        self.assertEqual((st["phase"], st["device"]), ("done", "cpu"), st.get("error"))
        self.assertIn("stopped unexpectedly", st["note"])
        self.assertTrue(all(t.startswith("cpu ") for _, t in texts(self.p)))

    def test_after_a_crash_the_next_run_gets_a_fresh_engine(self):
        job = Job(self.p, IsolatedEngine)
        for want in ("error", "done"):
            self.assertEqual(job.start({"speakers": [self.sid], "model": "crash-once", "device": "cpu"}), {"ok": True})
            job._thread.join(10)
            self.assertEqual(job.status()["phase"], want, job.status().get("error"))
        self.assertTrue(all(t.startswith("cpu ") for _, t in texts(self.p)))

    def test_cancel_with_the_child_process_keeps_old_lines_and_the_engine_usable(self):
        job = Job(self.p, IsolatedEngine)
        for cancel in (True, False):
            self.assertEqual(job.start({"speakers": [self.sid], "model": "slow", "device": "cpu"}), {"ok": True})
            while cancel and not job.status().get("recent"):
                time.sleep(0.02)
            if cancel:
                job.cancel()
            job._thread.join(10)
            self.assertEqual(job.status()["phase"], "cancelled" if cancel else "done")
            self.assertEqual(len(texts(self.p)), 1 if cancel else 40)

    def test_crash_on_the_processor_ends_the_run_with_an_error(self):
        st = self.run_job(IsolatedEngine, model="crash-always", device="cpu").status()
        self.assertEqual(st["phase"], "error")
        self.assertIn("stopped unexpectedly", st["error"])
        self.assertEqual([t for _, t in texts(self.p)], ["old"])

    def test_start_validation(self):
        class Missing(FakeEngine):
            available = staticmethod(lambda: False)
        self.assertIn("not installed", Job(self.p, Missing).start({"speakers": [self.sid]})["error"])
        self.assertEqual(Job(self.p, FakeEngine).start({"speakers": ["nope"]}), {"error": "Choose at least one person"})
        self.assertEqual(Job(self.p, FakeEngine).status(), {})

    def test_thai_model_must_be_installed(self):
        err = Job(self.p, FakeEngine).start({"speakers": [self.sid], "model": "typhoon"})["error"]
        self.assertIn("python convert_model.py typhoon", err)
        folder = convert_model.output_dir("typhoon", self.p.dir)
        folder.mkdir(parents=True)
        (folder / "model.bin").write_bytes(b"")
        err = Job(self.p, FakeEngine).start({"speakers": [self.sid], "model": "typhoon"})["error"]
        self.assertIn("incomplete", err)
        self.assertIn("preprocessor_config.json", err)
        self.assertIn("python convert_model.py typhoon", err)
        for f in MODEL_FILES:
            (folder / f).write_bytes(b"")
        loaded = []

        class Recording(FakeEngine):
            def __init__(self, model_name, *a):
                loaded.append(model_name)
                super().__init__(model_name, *a)
        job = Job(self.p, Recording)
        self.assertEqual(job.start({"speakers": [self.sid], "model": "typhoon"}), {"ok": True})
        job._thread.join(10)
        self.assertEqual(loaded, [str(folder)])
        self.assertEqual(job.status()["model"], "typhoon")


if __name__ == "__main__":
    unittest.main()

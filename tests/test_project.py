import io
import json
import tempfile
import unittest
import zipfile
from pathlib import Path

from helpers import pw, seg, texts, upload, wav

from craig_transcriber.project import Project


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
        self.p.edit_lines(
            [{"id": l1, "text": "HELLO", "ok": True, "start": 0.123, "end": -1}, {"id": "nope"}]
        )
        new = self.p.add_line_after(l1)
        self.assertIsNone(self.p.add_line_after("nope"))
        self.p.delete_line(self.p.state()["lines"][-1]["id"])
        self.p.rename_speaker(a, "  Alice ")
        self.p.rename_speaker(b, "   ")
        q = Project(self.dir)
        first = q.state()["lines"][0]
        self.assertEqual(
            (first["text"], first["ok"], first["start"], first["end"]), ("HELLO", True, 0.12, 1.0)
        )
        self.assertIn(new["id"], [ln["id"] for ln in q.state()["lines"]])
        self.assertEqual([s["name"] for s in q.state()["speakers"]], ["Alice", "b"])
        path = q.audio(b)[0]
        q.remove_speaker(b)
        self.assertFalse(path.exists())
        r = Project(self.dir)
        self.assertEqual([s["id"] for s in r.state()["speakers"]], [a])
        self.assertTrue(all(ln["spk"] == a for ln in r.state()["lines"]))

    def test_replace_lines_only_that_speaker(self):
        a, b = self.two()
        self.p.replace_lines(a, [seg(9, "new")], duration=12.5)
        self.assertEqual(texts(Project(self.dir)), [(b, "other"), (a, "new")])
        self.assertEqual(self.p.speaker(a)["duration"], 12.5)
        self.p.replace_lines("gone", [seg(0, "x")])
        self.assertEqual(len(self.p.state()["lines"]), 2)

    def test_replace_stretch_swaps_only_the_lines_whose_midpoint_is_inside(self):
        a, b = self.two()
        self.p.replace_lines(
            a,
            [seg(0, "a"), seg(5, "b"), seg(8.4, "edge"), seg(10, "c"), seg(20, "d")],
            30.0,
            {"model": "m"},
            [[0.0, 25.0]],
        )
        self.p.dismiss_missed(a, 6, 8)
        by = {ln["text"]: ln["id"] for ln in self.p.state()["lines"]}
        self.p.edit_lines([{"id": by["a"], "text": "a fixed"}, {"id": by["d"], "ok": True}])
        self.p.replace_stretch(a, 9, 12, [seg(8, "outside"), seg(9.6, "new1"), seg(11, "new2")])
        st = Project(self.dir).state()
        self.assertEqual(
            [ln["text"] for ln in st["lines"] if ln["spk"] == a],
            ["a fixed", "b", "edge", "new1", "new2", "d"],
        )
        self.assertEqual([ln["text"] for ln in st["lines"] if ln["spk"] == b], ["other"])
        new = {ln["text"]: ln for ln in st["lines"]}
        self.assertEqual((new["a fixed"]["edited"], new["d"]["ok"]), (True, True))
        self.assertEqual(
            (new["new1"]["ok"], new["new1"]["edited"], new["new1"]["id"] in by.values()),
            (False, False, False),
        )
        sp = self.p.speaker(a)
        self.assertEqual(
            (sp["run"], sp["speech"], sp["dismissed"], sp["duration"]),
            ({"model": "m"}, [[0.0, 25.0]], [[6, 8]], 30.0),
        )
        self.p.replace_stretch("gone", 0, 99, [seg(0, "x")])
        self.assertEqual(len(self.p.state()["lines"]), 7)

    def test_touched_speakers_are_reported(self):
        a, b = self.two()

        def touched():
            return {s["id"]: s["touched"] for s in self.p.state()["speakers"]}

        self.assertEqual(touched(), {a: False, b: False})
        la, lb = [ln["id"] for ln in self.p.state()["lines"] if ln["text"] in ("hello", "other")]
        self.p.edit_lines([{"id": la, "text": "hello there"}, {"id": lb, "ok": True}])
        self.assertEqual(touched(), {a: True, b: True})
        self.p.edit_lines([{"id": la, "text": "hello"}, {"id": lb, "ok": False}])
        self.assertEqual(touched(), {a: False, b: False})
        self.p.edit_lines([{"id": self.p.add_line_after(lb)["id"], "text": "added by hand"}])
        self.assertEqual(touched(), {a: False, b: True})
        self.p.delete_line([ln["id"] for ln in self.p.state()["lines"] if ln["text"] == "world"][0])
        self.assertEqual(touched(), {a: True, b: True})
        self.p.replace_lines(a, [seg(0, "fresh")])
        self.assertEqual(touched(), {a: False, b: True})

    def test_run_record_is_cleared_with_the_last_line(self):
        a, _ = self.two()
        self.p.replace_lines(a, [seg(0, "only")], run={"model": "m", "language": "th", "at": 1.0})
        self.p.delete_line(next(ln["id"] for ln in self.p.state()["lines"] if ln["spk"] == a))
        self.assertNotIn("run", Project(self.dir).speaker(a))

    def test_missed_speech_is_voice_no_line_covers_for_two_seconds_or_more(self):
        a, b = self.two()
        speech = [[0, 10], [20, 21], [30, 40], [50, 53], [60, 64]]
        self.p.replace_lines(
            a,
            [
                seg(0, "x"),
                seg(5, "y"),
                seg(31, "z"),
                seg(51.5, "w"),
                {"start": 58, "end": 61, "text": "v"},
            ],
            speech=speech,
        )

        def missed(sid):
            return next(
                s["missed"] for s in Project(self.dir).state()["speakers"] if s["id"] == sid
            )

        self.assertEqual(
            missed(a),
            [
                {"start": 1, "end": 5},
                {"start": 6, "end": 10},
                {"start": 32, "end": 40},
                {"start": 61, "end": 64},
            ],
        )
        self.assertEqual(missed(b), [])

    def test_dismissed_missed_speech_stays_gone_until_the_next_full_run(self):
        a, _ = self.two()
        self.p.replace_lines(a, [seg(0, "x")], speech=[[0, 30]])

        def missed():
            return next(s["missed"] for s in Project(self.dir).state()["speakers"] if s["id"] == a)

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
        self.assertEqual(
            (line["spk"], line["start"], line["end"], line["text"], line["orig"]),
            (a, 1, 30, "", ""),
        )
        st = Project(self.dir).state()
        self.assertIn(line["id"], [ln["id"] for ln in st["lines"]])
        self.assertEqual(st["speakers"][0]["missed"], [])
        self.assertIsNone(self.p.add_line_at("nope", 1, 5))
        self.assertIsNone(self.p.add_line_at(b, 5, 5))

    def test_set_speech_saves_only_the_voice_record(self):
        a, b = self.two()
        self.p.dismiss_missed(a, 1, 5)
        before = self.p.state()
        self.p.set_speech(a, [[0, 30]])
        self.p.set_speech("nope", [[0, 1]])
        after = Project(self.dir).state()
        self.assertEqual(after["lines"], before["lines"])

        def strip(st):
            return [
                {k: v for k, v in s.items() if k not in ("speech", "missed")}
                for s in st["speakers"]
            ]

        self.assertEqual(strip(after), strip(before))
        self.assertEqual(after["speakers"][0]["speech"], [[0, 30]])
        self.assertEqual(after["speakers"][0]["missed"], [{"start": 6, "end": 30}])
        self.assertNotIn("speech", after["speakers"][1])

    def test_speaker_without_speech_has_no_missed_speech_and_exports_ignore_it(self):
        a, b = self.two()
        before = [self.p.export(k) for k in ("txt", "srt", "json")]
        self.assertEqual([s["missed"] for s in self.p.state()["speakers"]], [[], []])
        self.p.replace_lines(a, [seg(0, "hello"), seg(5, "world")], speech=[[0, 30]])
        self.assertEqual(
            self.p.state()["speakers"][0]["missed"],
            [{"start": 1, "end": 5}, {"start": 6, "end": 30}],
        )
        self.assertEqual([self.p.export(k) for k in ("txt", "srt", "json")], before)
        self.p.replace_lines(a, [seg(0, "again")])
        self.assertEqual(self.p.speaker(a)["speech"], [[0, 30]])

    def test_every_line_carries_its_review_flags(self):
        upload(self.p, "1-a.wav", wav())
        sid = self.p.state()["speakers"][0]["id"]
        self.p.replace_lines(
            sid,
            [
                seg(0, "สวัสดีครับ"),
                seg(1, "ฟังไม่ชัด", conf=-1.2),
                seg(2, "อีเขียบ อีเขียบ อีเขียบ"),
                seg(3, "Essential Principal เลยนะเว้ย"),
                seg(4, "OK นะ"),
                seg(5, "แก้ทีหลัง"),
            ],
        )
        ids = {ln["text"]: ln["id"] for ln in self.p.state()["lines"]}
        self.p.edit_lines(
            [
                {"id": ids["อีเขียบ อีเขียบ อีเขียบ"], "text": "อีกแล้ว"},
                {"id": ids["แก้ทีหลัง"], "text": "แก้แล้ว"},
            ]
        )
        added = self.p.add_line_after(ids["แก้ทีหลัง"])["id"]
        self.p.edit_lines([{"id": added, "text": "พิมพ์เอง"}])
        self.p.add_line_after(added)
        flags = {
            ln["text"]: (ln["unsure"], ln["mixed"], ln["edited"])
            for ln in Project(self.dir).state()["lines"]
        }
        self.assertEqual(
            flags,
            {
                "สวัสดีครับ": (False, False, False),
                "ฟังไม่ชัด": (False, False, False),
                "อีกแล้ว": (False, False, True),
                "Essential Principal เลยนะเว้ย": (False, True, False),
                "OK นะ": (False, True, False),
                "แก้แล้ว": (False, False, True),
                "พิมพ์เอง": (False, False, True),
                "": (False, False, False),
            },
        )

    def test_old_lines_without_new_fields_get_flags(self):
        self.dir.mkdir()
        (self.dir / "project.json").write_text(
            json.dumps(
                {
                    "speakers": [
                        {
                            "id": "s1",
                            "name": "Old",
                            "file": "s1.flac",
                            "ext": ".flac",
                            "duration": None,
                            "source": "1-Old.flac",
                        }
                    ],
                    "lines": [
                        {
                            "id": "l2",
                            "spk": "s1",
                            "start": 1.0,
                            "end": 2.0,
                            "text": "hi there",
                            "conf": -1.5,
                            "ok": False,
                        }
                    ],
                    "seq": 2,
                }
            )
        )
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
        self.p.replace_lines(
            sid,
            [
                {
                    "start": i * 10.0,
                    "end": i * 10.0 + kw.pop("length", 5.0),
                    "text": text,
                    "conf": kw.pop("conf", -0.1),
                    **kw,
                }
                for i, (text, kw) in enumerate(lines)
            ],
        )
        return {ln["text"]: ln for ln in Project(self.dir).state()["lines"]}

    def test_each_cause_gives_its_own_reason(self):
        got = self.saved(
            ("fine words", dict(length=2.0, words=[pw(" fine"), pw(" words", 0.1)])),
            ("อีเขียบ" * 4, dict()),
            ("สวัสดี こんにちは", dict()),
            ("สวัสดีครับผมชื่อสมชายยินดีที่ได้รู้จัก", dict(length=1.0)),
            ("old flag", dict(suspect=True, length=2.0)),
            ("fine", dict(length=2.0)),
        )
        self.assertEqual(
            {t: (ln["reasons"], ln["unsure"]) for t, ln in got.items()},
            {
                "fine words": (["unsure word"], True),
                "อีเขียบ" * 4: (["repeated phrase"], True),
                "สวัสดี こんにちは": (["foreign letters"], True),
                "สวัสดีครับผมชื่อสมชายยินดีที่ได้รู้จัก": (["timing"], True),
                "old flag": ([], False),
                "fine": ([], False),
            },
        )

    def test_several_reasons_come_in_the_stated_order(self):
        text = "x こんにちは" + "ก" * 40
        got = self.saved((text, dict(length=1.0, words=[pw("x", 0.1), pw(" " + text[2:])])))
        self.assertEqual(
            got[text]["reasons"], ["unsure word", "repeated phrase", "foreign letters", "timing"]
        )

    def test_long_line_with_far_too_little_text_is_missed_speech(self):
        got = self.saved(
            ("าง", dict(length=14.0)),
            ("นี้", dict(length=9.0)),
            ("a perfectly normal line of speech", dict(length=14.0)),
            ("เพ", dict(length=3.9)),
            ("เพ ", dict(length=4.0)),
        )
        self.assertEqual(
            {t: ln["reasons"] for t, ln in got.items()},
            {
                "าง": ["missed speech"],
                "นี้": ["missed speech"],
                "a perfectly normal line of speech": [],
                "เพ": [],
                "เพ ": ["missed speech"],
            },
        )
        self.assertTrue(got["าง"]["unsure"])

    def test_empty_line_added_at_a_missed_stretch_is_not_missed_speech(self):
        upload(self.p, "1-a.wav", wav())
        sid = self.p.state()["speakers"][0]["id"]
        added = self.p.add_line_at(sid, 10.0, 20.0)
        line = next(ln for ln in self.p.state()["lines"] if ln["id"] == added["id"])
        self.assertEqual((line["unsure"], line["reasons"]), (False, []))

    def test_missed_speech_comes_after_the_other_reasons_and_editing_clears_it(self):
        got = self.saved(
            ("x こんにちは", dict(length=10.0, words=[pw("x", 0.1), pw(" こんにちは")])),
            ("าง", dict(length=14.0)),
        )
        self.assertEqual(
            got["x こんにちは"]["reasons"], ["unsure word", "foreign letters", "missed speech"]
        )
        self.p.edit_lines([{"id": ln["id"], "text": t + " แก้"} for t, ln in got.items()])
        self.assertEqual([ln["reasons"] for ln in self.p.state()["lines"]], [[], []])

    def test_editing_clears_unsure_reasons_and_underlines(self):
        got = self.saved(
            ("a b", dict(words=[pw(" a", 0.1), pw(" b")])),
            ("こんにちは", dict()),
            ("hello", dict(conf=-1.2)),
        )
        self.p.edit_lines([{"id": ln["id"], "text": t + " แก้"} for t, ln in got.items()])
        for ln in Project(self.dir).state()["lines"]:
            self.assertEqual(
                (ln["unsure"], ln["reasons"], ln["unsure_words"]), (False, [], []), ln["text"]
            )

    def test_lines_typed_by_hand_are_never_unsure(self):
        got = self.saved(("first", dict()))
        new = self.p.add_line_after(got["first"]["id"])["id"]
        self.p.edit_lines([{"id": new, "text": "こんにちは " + "ก" * 40}])
        line = next(ln for ln in Project(self.dir).state()["lines"] if ln["id"] == new)
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
        (self.dir / "project.json").write_text(
            json.dumps(
                {
                    "speakers": [
                        {
                            "id": "s1",
                            "name": "Old",
                            "file": "s1.flac",
                            "ext": ".flac",
                            "duration": None,
                            "source": "1-Old.flac",
                        }
                    ],
                    "lines": [
                        {
                            "id": "l2",
                            "spk": "s1",
                            "start": 1.5,
                            "end": 2.0,
                            "text": "hi",
                            "orig": "hi",
                            "conf": -0.2,
                            "ok": True,
                        }
                    ],
                    "seq": 2,
                }
            )
        )
        q = Project(self.dir)
        self.assertEqual(q.export("txt")[0], "[00:01] Old: hi\n")
        self.assertEqual(q.add_line_after("l2")["id"], "l3")
        (self.dir / "project.json").write_text("{broken")
        self.assertEqual(Project(self.dir).state()["lines"], [])


if __name__ == "__main__":
    unittest.main()

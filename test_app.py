import io
import json
import tempfile
import unittest
import wave
import zipfile
from pathlib import Path

from project import Project
from transcribe import Job, WhisperEngine, lines_from_segments, looks_hallucinated


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
        self.assertEqual(flags, {"สวัสดีครับ": (False, False, False), "ฟังไม่ชัด": (True, False, False),
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
        self.assertEqual((line["unsure"], line["mixed"], line["edited"]), (True, False, False))

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
        for text in ["แก ร ั ติ เลย อี เข ีย บ อี เข ีย บ อี เข ีย บ ไม่ ทัน พอ เล่น", "อีเขียบ อีเขียบ อีเขียบ",
                     "además habíaон", "складดิงตรงนี้", "เออ ตอนนี้一點ก็เดี๋ยว", "Mike is cursing too, Γειά"]:
            self.assertTrue(looks_hallucinated(text), text)

    def test_keeps_normal_thai_english_and_mixed(self):
        for text in ["เรียนแพทย์ดีกว่า", "No Way", "KMIT Open Courtware", "Essential Principal เลยนะเว้ย",
                     "อ่า ฮ่า ฮ่า ฮ่า", "เล่นๆ ตอนข้าง ตรงชีพหว่ะ", "เสียไป ๆ บางเมื่อ ๆ ๆ เยอะ ๆ", "เล่มละพัน 1,000 บาท?",
                     "Sami in år 2000", "Tiếng Việt", "นะนะนะนะนะ", "ไม่ไม่ไม่ไม่", "ฮ่าฮ่าฮ่าฮ่า", "ha ha ha ha",
                     "555555555", "1000000000"]:
            self.assertFalse(looks_hallucinated(text), text)


def w(text, start, end, prob=0.9):
    return {"text": text, "start": start, "end": end, "prob": prob}


def lines(*segments):
    return [(l["text"], round(l["start"], 2), round(l["end"], 2)) for l in lines_from_segments(segments)]


class LinesFromSegmentsTest(unittest.TestCase):
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


class FakeEngine:
    segments = [seg(0, " hello "), seg(1, ""), seg(2, "noise", conf=-1.5, no_speech=0.9), seg(3, "world")]
    job = None

    def __init__(self, model_name, prefer_cpu, on_status):
        self.device = "cpu"

    @staticmethod
    def available():
        return True

    def transcribe(self, path, language, prompt):
        return 4.0, iter(self.segments)


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

    def test_success_records_model_and_language(self):
        self.run_job(FakeEngine, language="th")
        run = Project(self.p.dir).speaker(self.sid)["run"]
        self.assertEqual((run["model"], run["language"]), ("m", "th"))
        self.assertGreater(run["at"], 0)

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

    def test_start_validation(self):
        class Missing(FakeEngine):
            available = staticmethod(lambda: False)
        self.assertIn("not installed", Job(self.p, Missing).start({"speakers": [self.sid]})["error"])
        self.assertEqual(Job(self.p, FakeEngine).start({"speakers": ["nope"]}), {"error": "Choose at least one person"})
        self.assertEqual(Job(self.p, FakeEngine).status(), {})

    def test_thai_model_must_be_installed(self):
        err = Job(self.p, FakeEngine).start({"speakers": [self.sid], "model": "typhoon"})["error"]
        self.assertIn("python convert_model.py typhoon", err)
        folder = self.p.dir / "models" / "typhoon"
        folder.mkdir(parents=True)
        (folder / "model.bin").write_bytes(b"")
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

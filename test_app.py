import io
import json
import tempfile
import unittest
import wave
import zipfile
from pathlib import Path

from project import Project
from transcribe import Job


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

    def run_job(self, engine_cls):
        job = Job(self.p, engine_cls)
        FakeEngine.job = job
        self.assertEqual(job.start({"speakers": [self.sid], "model": "m"}), {"ok": True})
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


if __name__ == "__main__":
    unittest.main()

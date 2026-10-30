import tempfile
import time
import unittest
from pathlib import Path

from helpers import FakeEngine, IsolatedEngine, pw, seg, texts, upload, w, wav

from craig_transcriber import convert_model
from craig_transcriber.project import Project
from craig_transcriber.transcribe import (
    CLIP_PAD,
    MODEL_FILES,
    Job,
)


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

            def transcribe(self, path, language, prompt, clip=None):
                raise RuntimeError("boom")

        class Cancelling(Boom):
            def transcribe(self, path, language, prompt, clip=None):
                FakeEngine.job.cancel()
                return FakeEngine.transcribe(self, path, language, prompt, clip)

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

    def stretch_setup(self):
        self.p.replace_lines(
            self.sid, [seg(0, "a"), seg(5, "b"), seg(10, "c"), seg(20, "d")], 30.0, {"model": "old"}, [[0.0, 25.0]]
        )
        by = {ln["text"]: ln["id"] for ln in self.p.state()["lines"]}
        self.p.edit_lines([{"id": by["c"], "text": "c fixed"}, {"id": by["b"], "ok": True}])
        self.before = self.p.state()
        return by

    def stretch_job(self, engine_cls, start=9, end=12, **opts):
        job = Job(self.p, engine_cls)
        FakeEngine.job = job
        self.assertEqual(
            job.start({"speakers": [self.sid], "start": start, "end": end, "model": "m", **opts}), {"ok": True}
        )
        job._thread.join(10)
        return job

    def test_stretch_run_asks_for_the_stretch_only_and_changes_only_lines_inside(self):
        self.stretch_setup()
        asked = []

        class Clipped(FakeEngine):
            segments = [seg(8.0, "outside here"), seg(9.5, "new one"), seg(10.5, "new two"), seg(12.0, "after here")]
            speech = [[99.0, 100.0]]

            def transcribe(self, path, language, prompt, clip=None):
                asked.append(clip)
                lo, hi = clip[0] - CLIP_PAD, clip[1] + CLIP_PAD
                return 30.0, iter([s for s in self.segments if s["start"] >= lo and s["end"] <= hi])

            def voice(self, path):
                raise AssertionError("a stretch run must not look for voice")

        job = self.stretch_job(Clipped, language="th", prompt="ขนุน")
        st = job.status()
        self.assertEqual((st["phase"], asked, st["dur"], st["pos"]), ("done", [(9.0, 12.0)], 3.0, 3.0))
        after = Project(self.p.dir).state()
        self.assertEqual([ln["text"] for ln in after["lines"]], ["a", "b", "new one", "new two", "d"])

        def keep(s):
            return [ln for ln in s["lines"] if ln["text"] in ("a", "b", "d")]

        self.assertEqual(keep(after), keep(self.before))
        self.assertTrue(
            all(not ln["ok"] and not ln["edited"] for ln in after["lines"] if ln["text"] in ("new one", "new two"))
        )
        sp = self.p.speaker(self.sid)
        self.assertEqual((sp["run"], sp["speech"], sp["duration"]), ({"model": "old"}, [[0.0, 25.0]], 30.0))

    def test_failed_cancelled_or_crashed_stretch_run_changes_nothing(self):
        self.stretch_setup()

        def saved():
            return (Project(self.p.dir).state(), self.p.speaker(self.sid))

        class Boom(FakeEngine):
            def transcribe(self, path, language, prompt, clip=None):
                def gen():
                    yield seg(10, "partial")
                    raise RuntimeError("boom")

                return 30.0, gen()

        class Cancelling(FakeEngine):
            def transcribe(self, path, language, prompt, clip=None):
                def gen():
                    yield seg(10, "first")
                    FakeEngine.job.cancel()
                    yield seg(11, "second")

                return 30.0, gen()

        want = saved()
        for engine_cls, phase in ((Boom, "error"), (Cancelling, "cancelled")):
            self.assertEqual(self.stretch_job(engine_cls).status()["phase"], phase)
            self.assertEqual(saved(), want)
        st = self.stretch_job(IsolatedEngine, model="crash-always", device="cpu").status()
        self.assertEqual(st["phase"], "error")
        self.assertIn("stopped unexpectedly", st["error"])
        self.assertEqual(saved(), want)

    def test_stretch_run_goes_through_the_child_process(self):
        self.stretch_setup()
        self.assertEqual(self.stretch_job(IsolatedEngine, model="clip", device="cpu").status()["phase"], "done")
        self.assertEqual([ln["text"] for ln in self.p.state()["lines"]], ["a", "b", "clip (9.0, 12.0)", "d"])

    def test_stretch_needs_exactly_one_person_and_a_real_range(self):
        upload(self.p, "2-b.wav", wav())
        ids = [s["id"] for s in self.p.state()["speakers"]]
        job = Job(self.p, FakeEngine)
        for opts in (
            {"speakers": ids, "start": 1, "end": 2},
            {"speakers": ["nope"], "start": 1, "end": 2},
            {"speakers": [], "start": 1, "end": 2},
            {"speakers": ids[:1], "start": 1},
            {"speakers": ids[:1], "start": 3, "end": 2},
            {"speakers": ids[:1], "start": -1, "end": 2},
            {"speakers": ids[:1], "start": "1", "end": 2},
            {"speakers": ids[:1], "start": 1, "end": 2, "check": True},
        ):
            self.assertIn("error", job.start(opts), opts)
        self.assertEqual(job.status(), {})

    def check_job(self, engine_cls, ids=None, **opts):
        job = Job(self.p, engine_cls)
        FakeEngine.job = job
        self.assertEqual(job.start({"speakers": ids or [self.sid], "check": True, **opts}), {"ok": True})
        job._thread.join(10)
        return job

    def test_check_saves_the_voice_and_leaves_lines_ticks_and_edits_alone(self):
        self.p.replace_lines(self.sid, [seg(0, "old"), seg(5, "later")], run={"model": "m", "at": 1.0})
        first = self.p.state()["lines"][0]["id"]
        self.p.edit_lines([{"id": first, "text": "fixed", "ok": True}])
        before = self.p.state()

        class NoTranscribing(FakeEngine):
            def transcribe(self, path, language, prompt, clip=None):
                raise AssertionError("a check must not transcribe")

        st = self.check_job(NoTranscribing).status()
        after = Project(self.p.dir).state()
        self.assertEqual((st["phase"], st["check"]), ("done", True))
        self.assertEqual(after["lines"], before["lines"])

        def strip(state):
            return [{k: v for k, v in s.items() if k not in ("speech", "missed")} for s in state["speakers"]]

        self.assertEqual(strip(after), strip(before))
        self.assertEqual(after["speakers"][0]["speech"], [[0.0, 3.5]])
        self.assertEqual(after["speakers"][0]["missed"], [{"start": 1.0, "end": 3.5}])

    def test_check_failure_changes_nothing_for_that_person_and_is_reported(self):
        upload(self.p, "2-b.wav", wav())
        ids = [s["id"] for s in self.p.state()["speakers"]]
        before = self.p.state()

        class OneNoVad(FakeEngine):
            def voice(self, path):
                if path.stem == ids[0]:
                    raise RuntimeError("vad broke")
                return super().voice(path)

        st = self.check_job(OneNoVad, ids).status()
        self.assertEqual(st["phase"], "done")
        self.assertIn("vad broke", st["note"])
        speakers = self.p.state()["speakers"]
        self.assertNotIn("speech", speakers[0])
        self.assertEqual(speakers[1]["speech"], [[0.0, 3.5]])
        self.assertEqual(self.p.state()["lines"], before["lines"])

    def test_check_cancel_stops_between_people(self):
        upload(self.p, "2-b.wav", wav())
        ids = [s["id"] for s in self.p.state()["speakers"]]

        class Cancelling(FakeEngine):
            def voice(self, path):
                FakeEngine.job.cancel()
                return super().voice(path)

        st = self.check_job(Cancelling, ids).status()
        self.assertEqual(st["phase"], "cancelled")
        speakers = self.p.state()["speakers"]
        self.assertEqual(["speech" in s for s in speakers], [True, False])

    def test_check_reuses_a_loaded_engine_whatever_model_is_chosen(self):
        loaded = []

        class Counting(FakeEngine):
            def __init__(self, model_name, *a):
                loaded.append(model_name)
                super().__init__(model_name, *a)

        job = Job(self.p, Counting)
        for opts in ({"model": "m"}, {"model": "other", "check": True}, {"model": "m"}):
            self.assertEqual(job.start({"speakers": [self.sid], **opts}), {"ok": True})
            job._thread.join(10)
        self.assertEqual(loaded, ["m"])

    def test_check_crash_ends_the_run_and_the_next_one_gets_a_fresh_engine(self):
        job = Job(self.p, IsolatedEngine)
        for model, want in (("crash-in-voice", "error"), ("m", "done")):
            self.assertEqual(
                job.start({"speakers": [self.sid], "check": True, "model": model, "device": "cpu"}), {"ok": True}
            )
            job._thread.join(10)
            self.assertEqual(job.status()["phase"], want, job.status().get("error"))
            if want == "error":
                self.assertIn("stopped unexpectedly", job.status()["error"])
                self.assertNotIn("speech", self.p.speaker(self.sid))
        self.assertEqual(self.p.speaker(self.sid)["speech"], [[0.0, 1.5]])
        self.assertEqual([t for _, t in texts(self.p)], ["old"])

    def test_words_reach_the_state(self):
        class Worded(FakeEngine):
            segments = [{**seg(0, "hello"), "words": [w("hello", 0.0, 0.5, 0.2)]}]

        self.run_job(Worded)
        self.assertEqual(self.p.state()["lines"][0]["words"], [pw("hello", 0.2)])

    def test_success_records_the_run_options(self):
        self.run_job(FakeEngine, language="th", prompt=" ขนุน, Go Fiber ")
        run = Project(self.p.dir).speaker(self.sid)["run"]
        self.assertEqual(
            {k: run[k] for k in ("model", "language", "vocabulary", "device")},
            {"model": "m", "language": "th", "vocabulary": "ขนุน, Go Fiber", "device": "cpu"},
        )
        self.assertGreater(run["at"], 0)

    def test_status_reports_audio_already_done_by_earlier_speakers(self):
        upload(self.p, "2-b.wav", wav())
        ids = [s["id"] for s in self.p.state()["speakers"]]
        seen = []

        class Watching(FakeEngine):
            def transcribe(self, path, language, prompt, clip=None):
                seen.append(FakeEngine.job.status()["audio_done"])
                return super().transcribe(path, language, prompt, clip)

        job = Job(self.p, Watching)
        FakeEngine.job = job
        self.assertEqual(job.start({"speakers": ids, "model": "m"}), {"ok": True})
        job._thread.join(10)
        self.assertEqual(seen, [0.0, 4.0])

    def test_vocabulary_reaches_engine(self):
        got = []

        class Listening(FakeEngine):
            def transcribe(self, path, language, prompt, clip=None):
                got.append((language, prompt))
                return super().transcribe(path, language, prompt, clip)

        self.run_job(Listening, language="th", prompt="  ขนุน, Go Fiber ")
        self.assertEqual(got, [("th", "ขนุน, Go Fiber")])

    def test_hallucinated_lines_are_kept_and_flagged(self):
        class Noisy(FakeEngine):
            segments = [seg(0, "สวัสดี"), seg(1, "อีเขียบ อีเขียบ อีเขียบ อีเขียบ"), seg(2, "además habíaон")]

        self.run_job(Noisy)
        lines = Project(self.p.dir).state()["lines"]
        self.assertEqual(
            [(ln["text"], ln["reasons"]) for ln in lines],
            [("สวัสดี", []), ("อีเขียบ อีเขียบ อีเขียบ อีเขียบ", ["repeated phrase"]), ("además habíaон", ["foreign letters"])],
        )

    def test_failed_or_cancelled_run_keeps_previous_record(self):
        self.run_job(FakeEngine, language="th")
        before = self.p.speaker(self.sid)["run"]

        class Boom(FakeEngine):
            def transcribe(self, path, language, prompt, clip=None):
                raise RuntimeError("boom")

        class Cancelling(FakeEngine):
            def transcribe(self, path, language, prompt, clip=None):
                FakeEngine.job.cancel()
                return super().transcribe(path, language, prompt, clip)

        for engine_cls in (Boom, Cancelling):
            self.run_job(engine_cls, language="en")
            self.assertEqual(self.p.speaker(self.sid)["run"], before)

    def test_failure_keeps_old_lines(self):
        class Boom(FakeEngine):
            def transcribe(self, path, language, prompt, clip=None):
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
            def transcribe(self, path, language, prompt, clip=None):
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

            def transcribe(self, path, language, prompt, clip=None):
                if self.device == "cuda":
                    raise RuntimeError("cuda died")
                return super().transcribe(path, language, prompt, clip)

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
        self.assertIn("python -m craig_transcriber.convert_model typhoon", err)
        folder = convert_model.output_dir("typhoon", self.p.dir)
        folder.mkdir(parents=True)
        (folder / "model.bin").write_bytes(b"")
        err = Job(self.p, FakeEngine).start({"speakers": [self.sid], "model": "typhoon"})["error"]
        self.assertIn("incomplete", err)
        self.assertIn("preprocessor_config.json", err)
        self.assertIn("python -m craig_transcriber.convert_model typhoon", err)
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

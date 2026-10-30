import os
import sys
import tempfile
import time
import types
import unittest
from pathlib import Path
from unittest import mock

from helpers import IsolatedEngine

from craig_transcriber.transcribe import (
    CLIP_PAD,
    MODEL_FILES,
    EngineCrashed,
    WhisperEngine,
    model_catalog,
)


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
        self.assertEqual(
            {n: (m["thai"], m.get("state")) for n, m in catalog.items() if m["thai"]},
            {"typhoon": (True, "installed"), "pathumma": (True, "incomplete")},
        )
        self.assertNotIn("state", catalog["large-v3"])
        self.assertEqual(
            {n for n, m in catalog.items() if m["slow"]},
            {"medium", "large-v3-turbo", "large-v3", "typhoon", "pathumma"},
        )
        self.assertEqual(
            {m["default"]: n for n, m in catalog.items() if m.get("default")},
            {"cpu": "small", "gpu": "large-v3"},
        )
        self.assertTrue(all(m["label"] for m in catalog.values()))

    def test_missing_thai_model(self):
        with tempfile.TemporaryDirectory() as d:
            self.assertEqual(
                {m["name"]: m.get("state") for m in model_catalog(d) if m["thai"]},
                {"typhoon": "missing", "pathumma": "missing"},
            )


class WhisperEngineTest(unittest.TestCase):
    def test_segments_carry_word_timings(self):
        word = type("W", (), {"start": 0.0, "end": 0.5, "word": " hi", "probability": 0.9})
        segment = type(
            "S",
            (),
            {
                "start": 0.0,
                "end": 1.0,
                "text": " hi",
                "avg_logprob": -0.2,
                "no_speech_prob": 0.1,
                "words": [word],
            },
        )

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
        self.assertEqual(
            list(segs)[0]["words"], [{"start": 0.0, "end": 0.5, "text": " hi", "prob": 0.9}]
        )

    def test_clip_cuts_the_padded_part_and_keeps_times_in_the_whole_audio(self):
        word = type("W", (), {"start": 0.5, "end": 1.0, "word": " hi", "probability": 0.9})
        segment = type(
            "S",
            (),
            {
                "start": 0.5,
                "end": 1.0,
                "text": " hi",
                "avg_logprob": -0.2,
                "no_speech_prob": 0.1,
                "words": [word],
            },
        )
        got = []

        class Model:
            def transcribe(self, audio, **kw):
                got.append((len(audio), kw))
                return iter([segment]), type("Info", (), {"language": "th"})

        class Engine(WhisperEngine):
            load_audio = staticmethod(lambda path: [0.0] * 16000 * 100)

            def _load(self, prefer_cpu):
                self._model, self.device = Model(), "cpu"

        engine = Engine("m", True, lambda **kw: None)
        for clip, secs, first in (
            ((10, 20), 12, 9.0),
            ((0.5, 5), 6.0, 0.0),
            ((97, 99.5), 4.0, 96.0),
        ):
            dur, segs = engine.transcribe("a.wav", "th", "", clip)
            seg0 = list(segs)[0]
            self.assertEqual(
                (dur, got[-1][0] / 16000, seg0["start"], seg0["words"][0]["end"]),
                (100.0, secs, first + 0.5, first + 1.0),
            )
        self.assertNotIn("clip_timestamps", got[-1][1])
        self.assertEqual(CLIP_PAD, 1.0)

    def test_voice_lists_seconds_with_voice(self):
        vad = types.ModuleType("faster_whisper.vad")
        vad.VadOptions = lambda **kw: kw
        vad.get_speech_timestamps = lambda audio, opts: (
            [{"start": 16000, "end": 40000}] if opts == {"min_silence_duration_ms": 500} else []
        )

        class Engine(WhisperEngine):
            load_audio = staticmethod(lambda path: [0.0] * 48000)

            def _load(self, prefer_cpu):
                pass

        with mock.patch.dict(
            sys.modules,
            {"faster_whisper": types.ModuleType("faster_whisper"), "faster_whisper.vad": vad},
        ):
            self.assertEqual(Engine("m", True, lambda **kw: None).voice("a.wav"), [[1.0, 2.5]])


class ProcessEngineTest(unittest.TestCase):
    def test_runs_in_a_child_process_and_streams_segments(self):
        notes = []
        engine = IsolatedEngine("ok", False, lambda **kw: notes.append(kw))
        dur, segs = engine.transcribe("a.wav", None, "")
        texts = [s["text"] for s in segs]
        self.assertEqual((dur, engine.device, engine.language, len(texts)), (4.0, "cuda", "th", 2))
        self.assertNotEqual(texts[0].split()[1], str(os.getpid()))
        self.assertIn({"message": "loaded on cuda"}, notes)

    def test_clip_goes_over_the_pipe(self):
        engine = IsolatedEngine("clip", True, lambda **kw: None)
        self.assertEqual(
            [s["text"] for s in engine.transcribe("a.wav", "th", "", (3.0, 4.5))[1]],
            ["clip (3.0, 4.5)"],
        )
        self.assertEqual(
            [s["text"] for s in engine.transcribe("a.wav", "th", "")[1]], ["clip None"]
        )

    def test_voice_goes_over_the_pipe_and_errors_and_crashes_come_back(self):
        engine = IsolatedEngine("ok", True, lambda **kw: None)
        self.assertEqual(engine.voice("a.wav"), [[0.0, 1.5]])
        self.assertEqual(
            next(engine.transcribe("a.wav", "th", "")[1])["text"].split()[2:], ["line", "0"]
        )
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
        self.assertEqual(
            next(engine.transcribe("a.wav", "th", "")[1])["text"].split()[2:], ["line", "0"]
        )


if __name__ == "__main__":
    unittest.main()

import io
import os
import time
import wave

from craig_transcriber.transcribe import (
    ProcessEngine,
)


def wav(seconds=0.2):
    b = io.BytesIO()
    with wave.open(b, "wb") as w:
        w.setnchannels(1), w.setsampwidth(2), w.setframerate(8000)
        w.writeframes(b"\0\0" * int(8000 * seconds))
    return b.getvalue()


def upload(p, name, data):
    return p.add_upload(io.BytesIO(data), len(data), name)


def texts(p):
    return [(ln["spk"], ln["text"]) for ln in p.state()["lines"]]


def seg(start, text, conf=-0.3, no_speech=0.0):
    return {"start": start, "end": start + 1, "text": text, "conf": conf, "no_speech": no_speech}


class ChildEngine:
    """Runs inside the child process of ProcessEngine; some model names crash it the way a CUDA abort does."""

    available = staticmethod(lambda: True)

    def __init__(self, model_name, prefer_cpu, on_status):
        if model_name == "crash-on-load" and not prefer_cpu:
            os._exit(134)
        self.model_name, self.device, self.language = model_name, "cpu" if prefer_cpu else "cuda", ""
        on_status(message=f"loaded on {self.device}")

    def transcribe(self, path, language, prompt, clip=None):
        if self.model_name == "clip":
            return 4.0, iter([seg(clip[0] if clip else 0, f"clip {clip}")])
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


class FakeEngine:
    segments = [seg(0, " hello "), seg(1, ""), seg(2, "noise", conf=-1.5, no_speech=0.9), seg(3, "world")]
    speech = [[0.0, 3.5]]
    job = None

    def __init__(self, model_name, prefer_cpu, on_status):
        self.device = "cpu"

    @staticmethod
    def available():
        return True

    def transcribe(self, path, language, prompt, clip=None):
        return 4.0, iter(self.segments)

    def voice(self, path):
        return self.speech


def w(text, start, end, prob=0.9):
    return {"text": text, "start": start, "end": end, "prob": prob}


def pw(text, prob=0.9):
    return {"text": text, "prob": prob}

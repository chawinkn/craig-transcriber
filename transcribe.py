import math
import multiprocessing
import os
import re
import threading
import time
import traceback
import weakref
from dataclasses import dataclass
from pathlib import Path

import project


def add_nvidia_dll_dirs():
    try:
        import importlib.util
        spec = importlib.util.find_spec("nvidia")
        bases = list(spec.submodule_search_locations) if spec and spec.submodule_search_locations else []
    except Exception:
        return
    for base in bases:
        if os.name == "nt":
            for d in Path(base).glob("*/bin"):
                try:
                    os.add_dll_directory(str(d))
                except Exception:
                    pass
                os.environ["PATH"] = str(d) + os.pathsep + os.environ.get("PATH", "")
        else:
            import ctypes
            for f in sorted(Path(base).glob("*/lib/lib*.so*")):
                try:
                    ctypes.CDLL(str(f), mode=ctypes.RTLD_GLOBAL)
                except Exception:
                    pass


def cuda_count():
    try:
        import ctranslate2
        return ctranslate2.get_cuda_device_count()
    except Exception:
        return 0


MODELS = [{"name": "small", "label": "Balanced (small, 0.5 GB)", "default": "cpu"},
          {"name": "medium", "label": "Better (medium, 1.5 GB)", "slow": True},
          {"name": "large-v3-turbo", "label": "Fast and good (turbo, 1.6 GB)", "slow": True},
          {"name": "large-v3", "label": "Most accurate (large-v3, 3 GB)", "slow": True, "default": "gpu"},
          {"name": "typhoon", "label": "Thai, most accurate (Typhoon large-v3, 3 GB)", "slow": True,
           "repo": "typhoon-ai/typhoon-whisper-large-v3"},
          {"name": "pathumma", "label": "Thai, noisy audio (Pathumma noise, 3 GB)", "slow": True,
           "repo": "PogusTheWhisper/Pathumma-whisper-th-large-v3-natural-noise-finetuned"}]
THAI_MODELS = {m["name"]: m["repo"] for m in MODELS if "repo" in m}
MODEL_FILES = ("model.bin", "config.json", "tokenizer.json", "preprocessor_config.json")   # what faster-whisper reads


def model_dir(data_dir, name):
    return Path(data_dir) / "models" / name


def thai_model_state(data_dir, name):
    """("installed" | "incomplete" | "missing", the files that are missing)."""
    missing = [f for f in MODEL_FILES if not (model_dir(data_dir, name) / f).exists()]
    return ("installed" if not missing else "missing" if len(missing) == len(MODEL_FILES) else "incomplete"), missing


def model_catalog(data_dir):
    """Every model the app offers; a Thai model also has "state": installed, incomplete or missing."""
    out = []
    for m in MODELS:
        entry = {"name": m["name"], "label": m["label"], "thai": "repo" in m, "slow": bool(m.get("slow"))}
        if m.get("default"):
            entry["default"] = m["default"]
        if entry["thai"]:
            entry["state"] = thai_model_state(data_dir, m["name"])[0]
        out.append(entry)
    return out


def looks_hallucinated(text):
    """A phrase of 4+ characters repeated 3+ times in a row, or letters that are neither Thai nor Latin."""
    if re.search(r"(.{4,}?)\1{2,}", re.sub(r"\s+", "", text)):
        return True
    # Latin: Basic through Extended-B (U+024F) plus Extended Additional (U+1E00-1EFF, Vietnamese).
    return any(ch.isalpha() and not ("\u0e00" <= ch <= "\u0e7f" or ch <= "\u024f" or "\u1e00" <= ch <= "\u1eff")
               for ch in text)


# No hallucination_silence_threshold: on noisy Thai audio it dropped ~70% of real speech (#4).
# PONYTAIL: no_repeat_ngram_size=10 measured on two one-minute clips only; retune with more recordings.
DECODE = dict(beam_size=5, vad_filter=True, vad_parameters=dict(min_silence_duration_ms=500),
              condition_on_previous_text=False, word_timestamps=True, no_repeat_ngram_size=10)

# Measured on one-minute Thai clips: pauses of 0.6 s keep every Line under 12 s; 30 chars/s is faster than anyone speaks.
LINE_GAP, LINE_MAX, LINE_MAX_CPS = 0.6, 12.0, 30.0


def _starts_word(words, j):
    """Thai "words" are token pieces: a piece starts a word after a space, or where Latin follows non-Latin."""
    text, prev = words[j]["text"], words[j - 1]["text"]
    latin = lambda ch: ch.isascii() and ch.isalpha()
    return text[:1].isspace() or (latin(text[:1]) and not latin(prev[-1:]))


_THAI_FOLLOWING = re.compile(r"[\u0e30-\u0e3a\u0e45\u0e47-\u0e4e]")  # vowels and marks written after a consonant
_THAI_LEADING = re.compile(r"[\u0e40-\u0e44]")                           # vowels written before it


def _splits_syllable(words, c):
    return bool(_THAI_FOLLOWING.match(words[c]["text"]) or _THAI_LEADING.match(words[c - 1]["text"][-1:]))


def _cut(words, lo, i, floor):
    """Index where a Line after the pause before words[i] begins: back to a word start within 3 pieces,
    else back past any split Thai syllable, but not below floor. The first piece of a word is often
    timed before the pause."""
    c = next((j for j in range(i, max(lo, i - 3), -1) if _starts_word(words, j)), None)
    if c is None:
        c = i
        while c > floor and c > i - 3 and _splits_syllable(words, c):
            c -= 1
    return c


def _cap(words, lo, hi, start, end):
    if end - start <= LINE_MAX or hi - lo < 2:
        return [(lo, hi, start, end)]
    i = max(range(lo + 1, hi), key=lambda k: words[k]["start"] - words[k - 1]["end"])
    c = _cut(words, lo, i, lo + 1)
    return _cap(words, lo, c, start, words[c - 1]["end"]) + _cap(words, c, hi, words[i]["start"], end)


def _spans(words):
    """(first, past-last, start, end) per Line, splitting at pauses of LINE_GAP and capping at LINE_MAX."""
    spans, lo, start = [], 0, words[0]["start"]
    for i in range(1, len(words)):
        if words[i]["start"] - words[i - 1]["end"] >= LINE_GAP:
            c = _cut(words, lo, i, lo)
            if c > lo:                  # else the whole previous stretch was a stray syllable piece: it joins this Line
                spans.append((lo, c, start, words[c - 1]["end"]))
            lo, start = c, words[i]["start"]
    spans.append((lo, len(words), start, words[-1]["end"]))
    return [part for span in spans for part in _cap(words, *span)]


def _line(start, end, text, conf):
    chars = len(re.sub(r"\s+", "", text))
    too_fast = chars >= 8 and chars / max(end - start, 0.01) > LINE_MAX_CPS
    return {"start": start, "end": end, "text": text, "conf": conf, "suspect": too_fast or looks_hallucinated(text)}


def lines_from_segments(segments):
    """Yield Lines from engine segments: drop silence and empty text, split long segments at pauses, flag suspects."""
    for seg in segments:
        text, conf = seg["text"].strip(), seg.get("conf")
        if not text or ((seg.get("no_speech") or 0) > 0.8 and conf is not None and conf < -1.0):
            continue
        words = seg.get("words") or []
        spans = _spans(words) if words else []
        if len(spans) < 2:
            yield _line(seg["start"], seg["end"], text, conf)
            continue
        for lo, hi, start, end in spans:
            part = "".join(w["text"] for w in words[lo:hi]).strip()
            if part:
                logs = [math.log(max(w["prob"], 1e-6)) for w in words[lo:hi]]
                yield _line(start, end, part, sum(logs) / len(logs))


class WhisperEngine:
    def __init__(self, model_name, prefer_cpu, on_status):
        self.model_name = model_name
        self.on_status = on_status
        self.device = None
        self.language = ""
        self._model = None
        self._load(prefer_cpu)

    @staticmethod
    def available():
        try:
            import faster_whisper  # noqa: F401
            return True
        except Exception:
            return False

    def _load(self, prefer_cpu):
        from faster_whisper import WhisperModel
        tries = [("cuda", "float16"), ("cuda", "int8_float16")] if not prefer_cpu and cuda_count() > 0 else []
        last = None
        for device, ctype in tries + [("cpu", "int8")]:
            try:
                self.on_status(message=f"Loading the model on the {'graphics card' if device == 'cuda' else 'processor'}. "
                                       "The first time, it is downloaded (up to a few GB); progress shows in the terminal window.")
                self._model = WhisperModel(self.model_name, device=device, compute_type=ctype)
                self.device = device
                return
            except Exception as e:
                last = e
                self.on_status(note=f"Could not use the {device} ({str(e)[:160]}). Trying the next option.")
        raise last

    def use_cpu(self):
        self._model = None                      # free the graphics card memory first
        self._load(True)

    @staticmethod
    def load_audio(path):
        # We decode ourselves because some PyAV versions break faster-whisper's own loader.
        import av
        import numpy as np
        resampler = av.AudioResampler(format="s16", layout="mono", rate=16000)
        chunks = []
        with av.open(str(path)) as c:
            for frame in c.decode(c.streams.audio[0]):
                for f in resampler.resample(frame):
                    chunks.append(f.to_ndarray().reshape(-1))
        for f in resampler.resample(None) or []:
            chunks.append(f.to_ndarray().reshape(-1))
        if not chunks:
            raise RuntimeError("no audio could be read from this file")
        return np.concatenate(chunks).astype(np.float32) / 32768.0

    def transcribe(self, audio_path, language, prompt):
        """(duration in seconds, iterator of {start, end, text, conf, no_speech, words}). Sets self.language."""
        audio = self.load_audio(audio_path)
        segments, info = self._model.transcribe(audio, language=language or None, initial_prompt=prompt or None,
                                                hotwords=prompt or None, **DECODE)
        self.language = getattr(info, "language", "")
        return len(audio) / 16000.0, ({"start": float(s.start), "end": float(s.end), "text": s.text,
                                       "conf": getattr(s, "avg_logprob", None),
                                       "no_speech": getattr(s, "no_speech_prob", 0) or 0,
                                       "words": [{"start": float(w.start), "end": float(w.end), "text": w.word,
                                                  "prob": float(w.probability)} for w in (getattr(s, "words", None) or [])]}
                                      for s in segments)


def _engine_worker(conn, inner, model_name, prefer_cpu):
    """Child process: own the inner engine and answer transcribe requests, streaming segments back."""
    add_nvidia_dll_dirs()
    try:
        engine = inner(model_name, prefer_cpu, lambda **kw: conn.send(("status", kw)))
    except Exception as e:
        conn.send(("failed", f"{type(e).__name__}: {e}"))
        return
    conn.send(("ready", engine.device))
    while True:
        try:
            msg = conn.recv()
        except EOFError:
            return
        if msg[0] != "transcribe":
            continue                                # a cancel that arrived after the run had already ended
        try:
            dur, segments = engine.transcribe(*msg[1:])
            conn.send(("start", dur, getattr(engine, "language", "")))
            for seg in segments:
                if conn.poll() and conn.recv()[0] == "cancel":
                    break
                conn.send(("seg", seg))
            conn.send(("end",))
        except Exception as e:
            conn.send(("error", f"{type(e).__name__}: {e}"))


def _stop_child(proc, conn):
    conn.close()
    proc.terminate()
    proc.join(5)


class EngineCrashed(RuntimeError):
    pass


class ProcessEngine:
    """The engine interface with INNER running in a child process, so a native crash there (a CUDA abort)
    becomes an error here instead of killing the server. The child, and its loaded model, lives as long as this."""
    INNER = WhisperEngine

    @classmethod
    def available(cls):
        return cls.INNER.available()

    def __init__(self, model_name, prefer_cpu, on_status):
        self.model_name, self.on_status, self.language, self.device = model_name, on_status, "", None
        try:
            self._start(prefer_cpu)
        except EngineCrashed:
            if prefer_cpu:
                raise
            self._stop()
            on_status(note="The graphics card crashed while loading the model. Trying the processor, which is slower.")
            self._start(True)

    def _start(self, prefer_cpu):
        ctx = multiprocessing.get_context("spawn")
        self._conn, child = ctx.Pipe()
        self._proc = ctx.Process(target=_engine_worker, args=(child, self.INNER, self.model_name, prefer_cpu),
                                 daemon=True)
        self._proc.start()
        child.close()
        self._stop = weakref.finalize(self, _stop_child, self._proc, self._conn)
        kind, rest = self._recv()
        if kind == "failed":
            raise RuntimeError(rest[0])
        self.device = rest[0]

    def _recv(self):
        """Next message other than a status update, which goes straight to on_status."""
        while True:
            try:
                kind, *rest = self._conn.recv()
            except (EOFError, OSError):
                self._proc.join(5)
                raise EngineCrashed(f"the transcription process stopped unexpectedly "
                                    f"(exit code {self._proc.exitcode})") from None
            if kind != "status":
                return kind, rest
            self.on_status(**rest[0])

    def use_cpu(self):
        self._stop()
        self._start(True)

    def transcribe(self, audio_path, language, prompt):
        self._conn.send(("transcribe", str(audio_path), language, prompt))
        kind, rest = self._recv()
        if kind == "error":
            raise RuntimeError(rest[0])
        dur, self.language = rest
        return dur, _SegmentStream(self)


class _SegmentStream:
    """Segments from the child. close() before the end (a cancel) stops the child's run and reads up to its end,
    so the pipe is clean for the next run, even if no segment was read yet."""

    def __init__(self, engine):
        self._engine, self._open = engine, True

    def __iter__(self):
        return self

    def __next__(self):
        if not self._open:
            raise StopIteration
        try:
            kind, rest = self._engine._recv()
        except EngineCrashed:
            self._open = False
            raise
        if kind == "seg":
            return rest[0]
        self._open = False
        if kind == "error":
            raise RuntimeError(rest[0])
        raise StopIteration

    def close(self):
        if self._open:
            self._open = False
            self._engine._conn.send(("cancel",))
            while self._engine._recv()[0] not in ("end", "error"):
                pass


@dataclass(frozen=True)
class RunOptions:
    model: str           # what the user chose, as shown and saved
    source: str          # what the engine loads: the same name, or a Thai model's folder
    language: "str | None"
    prefer_cpu: bool
    prompt: str


class Job:
    def __init__(self, project, engine_cls=ProcessEngine):
        self.project, self.engine_cls = project, engine_cls
        self._lock = threading.Lock()
        self._st = {}
        self._engine, self._engine_key = None, None
        self._thread = None

    @property
    def running(self):
        return bool(self._st.get("running"))

    @property
    def _cancelled(self):
        return bool(self._st.get("cancel"))

    def status(self):
        with self._lock:
            s = dict(self._st)
        if s:
            s["elapsed"] = time.time() - self._t0
        return s

    def cancel(self):
        self._set(cancel=True)

    def _set(self, **kw):
        with self._lock:
            self._st.update(kw)

    def _on_status(self, message=None, note=None):
        if message is not None:
            self._set(message=message)
        if note is not None:
            self._set(note=note)

    def start(self, opts):
        with self._lock:
            if self.running:
                return {"error": "Already running"}
            if not self.engine_cls.available():
                return {"error": "faster-whisper is not installed. Run: pip install faster-whisper"}
            ids = [i for i in opts.get("speakers", []) if self.project.speaker(i)]
            if not ids:
                return {"error": "Choose at least one person"}
            model = source = opts.get("model") or "small"
            if model in THAI_MODELS:
                state, missing = thai_model_state(self.project.dir, model)
                if state == "missing":
                    return {"error": f"The {model} model is not installed yet. Run: python convert_model.py {model}"}
                if state == "incomplete":
                    return {"error": f"The {model} model is incomplete (missing {', '.join(missing)}). "
                                     f"Run again: python convert_model.py {model}"}
                source = str(model_dir(self.project.dir, model))
            self._t0 = time.time()
            run = RunOptions(model, source, opts.get("language") or None, opts.get("device") == "cpu",
                             (opts.get("prompt") or "").strip())
            self._st = dict(running=True, cancel=False, phase="loading", message="Starting…", note="", error=None,
                            recent=[], pos=0.0, dur=0.0, audio_done=0.0, index=0, count=len(ids), who="", model=model)
            self._thread = threading.Thread(target=self._run, daemon=True, args=(ids, run))
            self._thread.start()
        return {"ok": True}

    def _run(self, ids, run):
        t_start = time.time()
        try:
            self._set(phase="loading", message="Getting the model ready…")
            key = (run.source, run.prefer_cpu)
            if self._engine_key != key:
                self._engine = self._engine_key = None
                self._engine = self.engine_cls(run.source, run.prefer_cpu, self._on_status)
                self._engine_key = key
            engine = self._engine
            self._set(device=engine.device)
            self._t0, done = time.time(), 0.0
            for idx, sid in enumerate(ids):
                sp = self.project.speaker(sid)
                if not sp or self._cancelled:
                    break
                self._set(phase="working", who=sp["name"], index=idx, count=len(ids), pos=0.0, audio_done=done,
                          dur=sp.get("duration") or 0.0, message="")
                for attempt in (0, 1):
                    try:
                        done += self._transcribe(engine, sid, sp["name"], run)
                        break
                    except Exception as e:
                        if isinstance(e, EngineCrashed):
                            self._engine = self._engine_key = None     # its process is gone; never reuse it
                        if engine.device == "cuda" and attempt == 0 and not self._cancelled:
                            self._set(note=f"The graphics card failed while working ({str(e)[:160]}). "
                                           "Switching to the processor, which is slower.")
                            self._engine_key = None
                            engine.use_cpu()
                            self._engine, self._engine_key = engine, (run.source, True)
                            self._set(device=engine.device)
                            continue
                        raise
            self._set(phase="cancelled" if self._cancelled else "done", message="", seconds=round(time.time() - t_start))
        except Exception as e:
            self._set(phase="error", error=f"{type(e).__name__}: {e}", trace=traceback.format_exc()[-1500:])
        finally:
            self._set(running=False)

    def _transcribe(self, engine, sid, name, run):
        """One person: collect their lines locally, and only a finished run replaces the old ones.
        Returns the audio length, so the estimate can count what earlier speakers took."""
        a = self.project.audio(sid)
        if not a:
            raise RuntimeError(f"the audio file for {name} is missing")
        self._set(message=f"Reading {name}'s audio…")
        dur, segments = engine.transcribe(a[0], run.language, run.prompt)
        try:
            return self._collect(engine, sid, name, run, dur, segments)
        finally:
            getattr(segments, "close", lambda: None)()

    def _collect(self, engine, sid, name, run, dur, segments):
        self._set(dur=dur, message="")
        detected = "" if run.language else getattr(engine, "language", "")
        if not run.language:
            self._set(detected=detected)
        kept = []
        for line in lines_from_segments(segments):
            if self._cancelled:
                return dur                          # keep their previous lines
            self._set(pos=float(line["end"]))
            kept.append(line)
            with self._lock:
                self._st["recent"] = (self._st["recent"] + [f"{name} [{project.hms(line['start'])}] {line['text']}"])[-4:]
        if not self._cancelled:
            record = {"model": run.model, "language": run.language or "auto", "vocabulary": run.prompt,
                      "device": engine.device, "at": time.time()}
            if not run.language:
                record["detected"] = detected
            self.project.replace_lines(sid, kept, dur, record)
        return dur

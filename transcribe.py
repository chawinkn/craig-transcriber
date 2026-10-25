import os
import re
import threading
import time
import traceback
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


THAI_MODELS = {"typhoon": "typhoon-ai/typhoon-whisper-large-v3",
               "pathumma": "PogusTheWhisper/Pathumma-whisper-th-large-v3-natural-noise-finetuned"}


def installed_thai_models(data_dir):
    """{name: folder} for the Thai models convert_model.py has written under <data_dir>/models."""
    dirs = {name: Path(data_dir) / "models" / name for name in THAI_MODELS}
    return {name: str(d) for name, d in dirs.items() if (d / "model.bin").exists()}


def looks_hallucinated(text):
    """A phrase of 4+ characters repeated 3+ times in a row, or letters that are neither Thai nor Latin."""
    if re.search(r"(.{4,}?)\1{2,}", re.sub(r"\s+", "", text)):
        return True
    # Latin: Basic through Extended-B (U+024F) plus Extended Additional (U+1E00-1EFF, Vietnamese).
    return any(ch.isalpha() and not ("\u0e00" <= ch <= "\u0e7f" or ch <= "\u024f" or "\u1e00" <= ch <= "\u1eff")
               for ch in text)


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
        """(duration in seconds, iterator of {start, end, text, conf, no_speech}). Sets self.language."""
        audio = self.load_audio(audio_path)
        segments, info = self._model.transcribe(
            audio, language=language or None, beam_size=5, vad_filter=True,
            vad_parameters=dict(min_silence_duration_ms=500), condition_on_previous_text=False,
            initial_prompt=prompt or None, hotwords=prompt or None,
            # PONYTAIL: thresholds not yet tuned on real noisy Thai audio; revisit with issue #5's comparison.
            word_timestamps=True, hallucination_silence_threshold=2.0, no_repeat_ngram_size=10)
        self.language = getattr(info, "language", "")
        return len(audio) / 16000.0, ({"start": float(s.start), "end": float(s.end), "text": s.text,
                                       "conf": getattr(s, "avg_logprob", None),
                                       "no_speech": getattr(s, "no_speech_prob", 0) or 0} for s in segments)


class Job:
    def __init__(self, project, engine_cls=WhisperEngine):
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
                source = installed_thai_models(self.project.dir).get(model)
                if not source:
                    return {"error": f"The {model} model is not installed yet. Run: python convert_model.py {model}"}
            self._t0 = time.time()
            self._st = dict(running=True, cancel=False, phase="loading", message="Starting…", note="", error=None,
                            recent=[], pos=0.0, dur=0.0, index=0, count=len(ids), who="", model=model)
            self._thread = threading.Thread(target=self._run, daemon=True, args=(
                ids, source, opts.get("language") or None,
                opts.get("device") == "cpu", (opts.get("prompt") or "").strip()))
            self._thread.start()
        return {"ok": True}

    def _run(self, ids, model, language, prefer_cpu, prompt):
        t_start = time.time()
        try:
            self._set(phase="loading", message="Getting the model ready…")
            key = (model, prefer_cpu)
            if self._engine_key != key:
                self._engine = self._engine_key = None
                self._engine = self.engine_cls(model, prefer_cpu, self._on_status)
                self._engine_key = key
            engine = self._engine
            self._set(device=engine.device)
            self._t0 = time.time()
            for idx, sid in enumerate(ids):
                sp = self.project.speaker(sid)
                if not sp or self._cancelled:
                    break
                self._set(phase="working", who=sp["name"], index=idx, count=len(ids), pos=0.0,
                          dur=sp.get("duration") or 0.0, message="")
                for attempt in (0, 1):
                    try:
                        self._transcribe(engine, sid, sp["name"], language, prompt)
                        break
                    except Exception as e:
                        if engine.device == "cuda" and attempt == 0 and not self._cancelled:
                            self._set(note=f"The graphics card failed while working ({str(e)[:160]}). "
                                           "Switching to the processor, which is slower.")
                            self._engine_key = None
                            engine.use_cpu()
                            self._engine_key = (model, True)
                            self._set(device=engine.device)
                            continue
                        raise
            self._set(phase="cancelled" if self._cancelled else "done", message="", seconds=round(time.time() - t_start))
        except Exception as e:
            self._set(phase="error", error=f"{type(e).__name__}: {e}", trace=traceback.format_exc()[-1500:])
        finally:
            self._set(running=False)

    def _transcribe(self, engine, sid, name, language, prompt):
        """One person: collect their lines locally, and only a finished run replaces the old ones."""
        a = self.project.audio(sid)
        if not a:
            raise RuntimeError(f"the audio file for {name} is missing")
        self._set(message=f"Reading {name}'s audio…")
        dur, segments = engine.transcribe(a[0], language, prompt)
        self._set(dur=dur, message="")
        detected = "" if language else getattr(engine, "language", "")
        if not language:
            self._set(detected=detected)
        kept = []
        for seg in segments:
            if self._cancelled:
                return                              # keep their previous lines
            self._set(pos=float(seg["end"]))
            text, conf = seg["text"].strip(), seg.get("conf")
            if not text or ((seg.get("no_speech") or 0) > 0.8 and conf is not None and conf < -1.0):
                continue
            kept.append({**seg, "text": text, "suspect": looks_hallucinated(text)})
            with self._lock:
                self._st["recent"] = (self._st["recent"] + [f"{name} [{project.hms(seg['start'])}] {text}"])[-4:]
        if not self._cancelled:
            with self._lock:
                run = {"model": self._st["model"], "language": language or "auto", "at": time.time()}
            if not language:
                run["detected"] = detected
            self.project.replace_lines(sid, kept, dur, run)

import copy
import json
import os
import re
import shutil
import tempfile
import threading
import zipfile
from pathlib import Path

AUDIO_EXT = {".flac", ".wav", ".mp3", ".ogg", ".oga", ".opus", ".m4a", ".aac", ".webm", ".mp4"}
MIME = {".flac": "audio/flac", ".wav": "audio/wav", ".mp3": "audio/mpeg", ".ogg": "audio/ogg",
        ".oga": "audio/ogg", ".opus": "audio/ogg", ".m4a": "audio/mp4", ".aac": "audio/aac",
        ".webm": "audio/webm", ".mp4": "audio/mp4"}


def hms(t):
    t = max(0, int(t))
    return f"{t // 3600:d}:{t % 3600 // 60:02d}:{t % 60:02d}" if t >= 3600 else f"{t // 60:02d}:{t % 60:02d}"


def srt_time(t):
    ms = int(round(t * 1000))
    return f"{ms // 3600000:02d}:{ms % 3600000 // 60000:02d}:{ms % 60000 // 1000:02d},{ms % 1000:03d}"


def speaker_name_from(filename):
    stem = Path(filename).stem
    return re.sub(r"^\d+[-_ ]+", "", stem) or stem          # Craig names files "1-name.flac"


def probe_duration(path):
    """Length in seconds, or None when the file does not say (streamed FLAC from Craig often doesn't)."""
    try:
        import av
        with av.open(str(path)) as c:
            if c.duration:
                return c.duration / 1_000_000
            st = c.streams.audio[0]
            if st.duration and st.time_base:
                return float(st.duration * st.time_base)
    except Exception:
        pass
    return None


class Project:
    def __init__(self, data_dir):
        self.dir = Path(data_dir)
        self._lock = threading.RLock()
        self._p = {"speakers": [], "lines": [], "seq": 0}
        try:
            d = json.loads((self.dir / "project.json").read_text(encoding="utf-8"))
            self._p["speakers"], self._p["lines"], self._p["seq"] = d["speakers"], d["lines"], d.get("seq", len(d["lines"]))
        except FileNotFoundError:
            pass
        except Exception as e:
            print("Could not read the saved project (starting empty):", e)

    def _save(self):
        self.dir.mkdir(parents=True, exist_ok=True)
        f = self.dir / "project.json"
        tmp = f.with_suffix(".tmp")
        tmp.write_text(json.dumps(self._p, ensure_ascii=False), encoding="utf-8")
        os.replace(tmp, f)

    def _new_id(self, prefix):
        self._p["seq"] += 1
        return f"{prefix}{self._p['seq']}"

    def _speaker(self, sid):
        return next((s for s in self._p["speakers"] if s["id"] == sid), None)

    def _line(self, line_id):
        return next((l for l in self._p["lines"] if l["id"] == line_id), None)

    def _sorted_lines(self):
        order = {s["id"]: i for i, s in enumerate(self._p["speakers"])}
        return sorted(self._p["lines"], key=lambda l: (l["start"], order.get(l["spk"], 0)))

    def state(self):
        """Speakers carry "touched": a line of theirs was reviewed or its text differs from the model's."""
        with self._lock:
            st = copy.deepcopy({"speakers": self._p["speakers"], "lines": self._sorted_lines()})
        touched = {l["spk"] for l in st["lines"] if l["ok"] or l["text"] != l.get("orig", l["text"])}
        for sp in st["speakers"]:
            sp["touched"] = sp["id"] in touched
        return st

    def speaker(self, sid):
        with self._lock:
            return copy.deepcopy(self._speaker(sid))

    def audio(self, sid):
        with self._lock:
            sp = self._speaker(sid)
            path = self.dir / "audio" / sp["file"] if sp else None
            mime = MIME.get(sp.get("ext", ""), "application/octet-stream") if sp else None
        return (path, mime) if path and path.exists() else None

    def export(self, kind):
        with self._lock:
            L = copy.deepcopy(self._sorted_lines())
            names = {s["id"]: s["name"] for s in self._p["speakers"]}
        if kind == "txt":
            return "\n".join(f"[{hms(l['start'])}] {names.get(l['spk'], '?')}: {l['text']}" for l in L) + "\n", "text/plain"
        if kind == "srt":
            out = [f"{i}\n{srt_time(l['start'])} --> {srt_time(max(l['end'], l['start'] + 0.3))}\n{names.get(l['spk'], '?')}: {l['text']}\n"
                   for i, l in enumerate(L, 1)]
            return "\n".join(out), "text/plain"
        data = [{"speaker": names.get(l["spk"], "?"), "start": l["start"], "end": l["end"], "text": l["text"],
                 "reviewed": l["ok"]} for l in L]
        return json.dumps(data, ensure_ascii=False, indent=1), "application/json"

    def add_upload(self, fileobj, length, name):
        name = Path(name).name or "audio"
        ext = Path(name).suffix.lower()
        (self.dir / "audio").mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=self.dir, suffix=".tmp")
        tmp = Path(tmp)
        try:
            with os.fdopen(fd, "wb") as f:
                left = length
                while left > 0:
                    chunk = fileobj.read(min(1 << 20, left))
                    if not chunk:
                        break
                    f.write(chunk)
                    left -= len(chunk)
            if ext == ".zip":
                added = self._add_zip(tmp)
                if not added:
                    raise ValueError(f"No audio files were found inside {name}.")
                return added
            if ext not in AUDIO_EXT:
                raise ValueError(f"{name}: not an audio file or .zip")
            with self._lock:
                sid = self._new_id("s")
            dest = self.dir / "audio" / f"{sid}{ext}"
            os.replace(tmp, dest)
            return [self._register(sid, dest, name)]
        except zipfile.BadZipFile:
            raise ValueError(f"{name} is not a valid .zip file")
        finally:
            tmp.unlink(missing_ok=True)

    def _add_zip(self, zip_path):
        added = []
        with zipfile.ZipFile(zip_path) as z:
            members = sorted((m for m in z.infolist() if not m.is_dir()
                              and Path(m.filename).suffix.lower() in AUDIO_EXT
                              and not Path(m.filename).name.startswith(".")),
                             key=lambda m: m.filename)
            for m in members:
                with self._lock:
                    sid = self._new_id("s")
                dest = self.dir / "audio" / f"{sid}{Path(m.filename).suffix.lower()}"
                with z.open(m) as fin, open(dest, "wb") as fout:
                    shutil.copyfileobj(fin, fout, 1 << 20)
                added.append(self._register(sid, dest, Path(m.filename).name))
        return added

    def _register(self, sid, dest, original_name):
        duration = probe_duration(dest)
        with self._lock:
            base = name = speaker_name_from(original_name)
            taken, n = {s["name"] for s in self._p["speakers"]}, 2
            while name in taken:
                name, n = f"{base} ({n})", n + 1
            self._p["speakers"].append({"id": sid, "name": name, "file": dest.name, "ext": dest.suffix.lower(),
                                        "duration": duration, "source": original_name})
            self._save()
        return name

    def edit_lines(self, updates):
        with self._lock:
            by = {l["id"]: l for l in self._p["lines"]}
            for u in updates:
                l = by.get(u.get("id"))
                if not l:
                    continue
                if isinstance(u.get("text"), str):
                    l["text"] = u["text"]
                if isinstance(u.get("ok"), bool):
                    l["ok"] = u["ok"]
                for k in ("start", "end"):
                    if isinstance(u.get(k), (int, float)) and u[k] >= 0:
                        l[k] = round(float(u[k]), 2)
            self._save()

    def add_line_after(self, line_id):
        with self._lock:
            after = self._line(line_id)
            if not after:
                return None
            line = {"id": self._new_id("l"), "spk": after["spk"], "start": after["end"],
                    "end": round(after["end"] + 2, 2), "text": "", "orig": "", "conf": None, "ok": False}
            self._p["lines"].append(line)
            self._save()
            return dict(line)

    def delete_line(self, line_id):
        with self._lock:
            self._p["lines"] = [l for l in self._p["lines"] if l["id"] != line_id]
            self._save()

    def rename_speaker(self, sid, name):
        with self._lock:
            sp = self._speaker(sid)
            if sp and isinstance(name, str) and name.strip():
                sp["name"] = name.strip()
                self._save()

    def remove_speaker(self, sid):
        with self._lock:
            sp = self._speaker(sid)
            if not sp:
                return
            self._p["speakers"] = [s for s in self._p["speakers"] if s["id"] != sid]
            self._p["lines"] = [l for l in self._p["lines"] if l["spk"] != sid]
            self._save()
        (self.dir / "audio" / sp["file"]).unlink(missing_ok=True)

    def replace_lines(self, sid, segments, duration=None, run=None):
        with self._lock:
            sp = self._speaker(sid)
            if not sp:
                return
            if duration is not None:
                sp["duration"] = duration
            if run is not None:
                sp["run"] = run
            self._p["lines"] = [l for l in self._p["lines"] if l["spk"] != sid]
            for s in segments:
                conf = s.get("conf")
                self._p["lines"].append({"id": self._new_id("l"), "spk": sid, "start": round(float(s["start"]), 2),
                                         "end": round(float(s["end"]), 2), "text": s["text"], "orig": s["text"],
                                         "conf": None if conf is None else round(float(conf), 3), "ok": False,
                                         "suspect": bool(s.get("suspect"))})
            self._save()

    def reset(self):
        """Forget everything. Only removes our own files (project.json, audio/), not the whole folder."""
        with self._lock:
            self._p.update(speakers=[], lines=[], seq=0)
            (self.dir / "project.json").unlink(missing_ok=True)
            shutil.rmtree(self.dir / "audio", ignore_errors=True)

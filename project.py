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


# Measured (#29) on 219 reviewed Lines of a 33-min Thai meeting, Pathumma: the lowest word probability in a Line was
# the best of the scores tried; under 0.3 tags 12% of Lines and catches 6 of 17 wrong ones (0 of 17 before).
UNSURE_WORD_PROB = 0.3


def unsure_spans(text, words):
    """[start, end) character spans in text of the words under UNSURE_WORD_PROB, found in order; touching ones merge."""
    spans, pos = [], 0
    for w in words:
        piece = w["text"].strip()
        i = text.find(piece, pos) if piece else -1
        if i < 0:
            continue
        pos = i + len(piece)
        if w["prob"] < UNSURE_WORD_PROB:
            if spans and spans[-1][1] == i:     # Thai word pieces touch: show them as one word
                spans[-1][1] = pos
            else:
                spans.append([i, pos])
    return spans


LINE_MAX_CPS = 30.0  # faster than anyone speaks
MISSED_MIN_SECONDS, MISSED_MAX_CPS = 4.0, 2.0  # on the 2026-10-29 recording: 3 Lines, all real dropped speech


def repeats(text):
    """A phrase of 4+ characters repeated 4+ times in a row."""
    return bool(re.search(r"(.{4,}?)\1{3,}", re.sub(r"\s+", "", text)))


def foreign_letters(text):
    """Letters that are neither Thai nor Latin. Latin: Basic through Extended-B (U+024F) plus Extended Additional (U+1E00-1EFF, Vietnamese)."""
    return any(ch.isalpha() and not ("\u0e00" <= ch <= "\u0e7f" or ch <= "\u024f" or "\u1e00" <= ch <= "\u1eff")
               for ch in text)


def too_fast(text, start, end):
    chars = len(re.sub(r"\s+", "", text))
    return chars >= 20 and chars / max(end - start, 0.01) > LINE_MAX_CPS


def too_slow(text, start, end):
    return end - start >= MISSED_MIN_SECONDS and len(re.sub(r"\s+", "", text)) / (end - start) < MISSED_MAX_CPS


def review_flags(line):
    """reasons: why the Line is unsure, in a fixed order; empty once the text differs from what the model wrote
    (edited, which includes Lines typed in by hand). The made-up causes are worked out again from the text and times,
    but only for Lines flagged suspect; a flag no rule explains (older runs) reads "looks made up". mixed: Thai with
    English. unsure_words: character spans in the text. "missed speech" comes last: a Line of 4 s or more with under
    2 characters per second."""
    text, words = line["text"], line.get("words")
    edited = text != line.get("orig", text)
    spans = [] if edited or not words else unsure_spans(text, words)
    reasons = []
    if not edited:
        if spans:
            reasons.append("unsure word")
        if line.get("suspect"):
            causes = [(repeats(text), "repeated phrase"), (foreign_letters(text), "foreign letters"),
                      (too_fast(text, line.get("start", 0), line.get("end", 0)), "timing")]
            reasons += [r for hit, r in causes if hit] or ["looks made up"]
        if too_slow(text, line.get("start", 0), line.get("end", 0)):
            reasons.append("missed speech")
    return {"edited": edited, "unsure_words": spans, "reasons": reasons, "unsure": bool(reasons),
            "mixed": bool(re.search(r"[\u0e00-\u0e7f]", text)) and len(re.findall(r"[A-Za-z]", text)) >= 2}


MISSED_MIN_GAP = 2.0   # seconds of voice with no Line over it that count as Missed speech


def missed_stretches(speech, spans):
    """Parts of the voice stretches [start, end] that no span covers, kept when MISSED_MIN_GAP or longer."""
    out, spans = [], sorted(spans)
    gap = lambda a, b: out.append({"start": round(a, 2), "end": round(b, 2)}) if round(b - a, 2) >= MISSED_MIN_GAP else None
    for start, end in speech:
        pos = start
        for s, e in spans:
            if e <= pos:
                continue
            if s >= end:
                break
            gap(pos, s)
            pos = max(pos, e)
        gap(pos, end)
    return out


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
        """Each Line carries its review flags; a Speaker is "touched" when a Line of theirs was reviewed,
        edited or deleted since the model wrote it, and has its Missed speech stretches."""
        with self._lock:
            st = copy.deepcopy({"speakers": self._p["speakers"], "lines": self._sorted_lines()})
        for l in st["lines"]:
            l.update(review_flags(l))
        touched = {l["spk"] for l in st["lines"] if l["ok"] or l["edited"]}
        for sp in st["speakers"]:
            sp["touched"] = sp["id"] in touched or bool(sp.pop("deleted_by_hand", False))
            gone = sp.get("dismissed") or []
            sp["missed"] = [m for m in missed_stretches(sp.get("speech") or [], [(l["start"], l["end"]) for l in st["lines"] if l["spk"] == sp["id"]])
                            if not any(a <= (m["start"] + m["end"]) / 2 <= b for a, b in gone)]
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

    def add_line_at(self, sid, start, end):
        with self._lock:
            nums = all(isinstance(x, (int, float)) and not isinstance(x, bool) for x in (start, end))
            if not self._speaker(sid) or not nums or not 0 <= start < end:
                return None
            line = {"id": self._new_id("l"), "spk": sid, "start": round(float(start), 2),
                    "end": round(float(end), 2), "text": "", "orig": "", "conf": None, "ok": False}
            self._p["lines"].append(line)
            self._save()
            return dict(line)

    def dismiss_missed(self, sid, start, end):
        with self._lock:
            sp = self._speaker(sid)
            if sp and all(isinstance(x, (int, float)) and not isinstance(x, bool) for x in (start, end)):
                sp.setdefault("dismissed", []).append([start, end])
                self._save()

    def delete_line(self, line_id):
        with self._lock:
            line = self._line(line_id)
            if not line:
                return
            self._p["lines"].remove(line)
            sp = self._speaker(line["spk"])
            if sp and line.get("orig"):
                sp["deleted_by_hand"] = True
            if sp and not any(l["spk"] == sp["id"] for l in self._p["lines"]):
                sp.pop("run", None)
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

    def replace_lines(self, sid, segments, duration=None, run=None, speech=None):
        with self._lock:
            sp = self._speaker(sid)
            if not sp:
                return
            if duration is not None:
                sp["duration"] = duration
            if run is not None:
                sp["run"] = run
            if speech is not None:
                sp["speech"] = speech
            sp.pop("deleted_by_hand", None)
            sp.pop("dismissed", None)
            self._p["lines"] = [l for l in self._p["lines"] if l["spk"] != sid]
            for s in segments:
                conf = s.get("conf")
                self._p["lines"].append({"id": self._new_id("l"), "spk": sid, "start": round(float(s["start"]), 2),
                                         "end": round(float(s["end"]), 2), "text": s["text"], "orig": s["text"],
                                         "conf": None if conf is None else round(float(conf), 3), "ok": False,
                                         "suspect": bool(s.get("suspect")),
                                         "words": [{"text": x["text"], "prob": round(float(x["prob"]), 3)}
                                                   for x in s.get("words") or []]})
            self._save()

    def set_speech(self, sid, speech):
        with self._lock:
            sp = self._speaker(sid)
            if sp:
                sp["speech"] = speech
                self._save()

    def reset(self):
        """Forget everything. Only removes our own files (project.json, audio/), not the whole folder."""
        with self._lock:
            self._p.update(speakers=[], lines=[], seq=0)
            (self.dir / "project.json").unlink(missing_ok=True)
            shutil.rmtree(self.dir / "audio", ignore_errors=True)

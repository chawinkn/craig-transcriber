import json
import re
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlparse

import transcribe

OK = {"ok": True}
STATIC = {
    "/": ("index.html", "text/html; charset=utf-8"),
    "/app.js": ("app.js", "text/javascript; charset=utf-8"),
    "/style.css": ("style.css", "text/css; charset=utf-8"),
}


def add_line(p, b):
    line = p.add_line_at(b.get("spk"), b.get("start"), b.get("end")) if "spk" in b else p.add_line_after(b.get("after"))
    return {"line": line} if line else ({"error": "Could not add a Line there"}, 400)


# JSON POST routes: path -> (project, job, body) -> response, or (response, status code). Mutators return None.
POST = {
    "/api/transcribe": lambda p, j, b: j.start(b),
    "/api/cancel": lambda p, j, b: j.cancel() or OK,
    "/api/lines": lambda p, j, b: p.edit_lines(b.get("updates", [])) or OK,
    "/api/line/delete": lambda p, j, b: p.delete_line(b.get("id")) or OK,
    "/api/line/add": lambda p, j, b: add_line(p, b),
    "/api/missed/dismiss": lambda p, j, b: p.dismiss_missed(b.get("spk"), b.get("start"), b.get("end")) or OK,
    "/api/speaker": lambda p, j, b: p.rename_speaker(b.get("id"), b.get("name")) or OK,
    "/api/speaker/remove": lambda p, j, b: p.remove_speaker(b.get("id")) or OK,
    "/api/reset": lambda p, j, b: ({"error": "Stop the transcription first"}, 400) if j.running else (p.reset() or OK),
}


def make_server(host, port, project, job):
    httpd = ThreadingHTTPServer((host, port), Handler)
    httpd.project, httpd.job = project, job
    return httpd


class Handler(BaseHTTPRequestHandler):
    server_version = "CraigTranscriber"

    project = property(lambda self: self.server.project)
    job = property(lambda self: self.server.job)

    def log_message(self, *a):
        pass

    def send_bytes(self, code, body, ctype, extra=None):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(body)

    def send_json(self, obj, code=200):
        self.send_bytes(code, json.dumps(obj, ensure_ascii=False).encode("utf-8"), "application/json; charset=utf-8")

    def read_json(self):
        n = int(self.headers.get("Content-Length") or 0)
        return json.loads(self.rfile.read(n) or b"{}")

    def allowed(self, post=False):
        """Block DNS rebinding (odd Host) and cross-site POSTs (odd Origin); else 403."""
        ok = urlparse("//" + self.headers.get("Host", "")).hostname in ("127.0.0.1", "localhost", "::1")
        o = self.headers.get("Origin")
        if post and o is not None:
            ok = ok and urlparse(o).netloc == self.headers.get("Host")
        if not ok:
            self.send_bytes(403, b"Forbidden", "text/plain")
        return ok

    def do_GET(self):
        if not self.allowed():
            return
        u = urlparse(self.path)
        try:
            if u.path in STATIC:
                name, ctype = STATIC[u.path]
                return self.send_bytes(200, (Path(__file__).parent / "static" / name).read_bytes(), ctype)
            if u.path == "/api/state":
                env = {"engine": self.job.engine_cls.available(), "cuda": transcribe.cuda_count(), "py": sys.version.split()[0],
                       "models": transcribe.model_catalog(self.project.dir)}
                return self.send_json({**self.project.state(), "env": env})
            if u.path == "/api/status":
                return self.send_json(self.job.status())
            if u.path.startswith("/audio/"):
                return self.serve_audio(u.path[7:])
            m = re.fullmatch(r"/export\.(txt|srt|json)", u.path)
            if m:
                body, ctype = self.project.export(m.group(1))
                return self.send_bytes(200, body.encode("utf-8"), ctype + "; charset=utf-8",
                                       {"Content-Disposition": f'attachment; filename="transcript.{m.group(1)}"'})
            self.send_bytes(404, b"Not found", "text/plain")
        except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
            pass

    def serve_audio(self, sid):
        a = self.project.audio(unquote(sid))
        if not a:
            return self.send_bytes(404, b"No such audio", "text/plain")
        path, mime = a
        size = path.stat().st_size
        start, end, code = 0, size - 1, 200
        rng = self.headers.get("Range")
        if rng:
            m = re.fullmatch(r"bytes=(\d*)-(\d*)", rng.strip())
            if m and (m.group(1) or m.group(2)):
                if m.group(1):
                    start = int(m.group(1))
                    end = int(m.group(2)) if m.group(2) else size - 1
                else:
                    start = max(0, size - int(m.group(2)))
                end = min(end, size - 1)
                if start > end:
                    return self.send_bytes(416, b"", "text/plain", {"Content-Range": f"bytes */{size}"})
                code = 206
        self.send_response(code)
        self.send_header("Content-Type", mime)
        self.send_header("Accept-Ranges", "bytes")
        self.send_header("Content-Length", str(end - start + 1))
        if code == 206:
            self.send_header("Content-Range", f"bytes {start}-{end}/{size}")
        self.end_headers()
        with open(path, "rb") as f:
            f.seek(start)
            left = end - start + 1
            while left > 0:
                chunk = f.read(min(1 << 20, left))
                if not chunk:
                    break
                self.wfile.write(chunk)
                left -= len(chunk)

    def do_POST(self):
        if not self.allowed(post=True):
            return
        u = urlparse(self.path)
        try:
            if u.path == "/api/upload":
                return self.upload(parse_qs(u.query).get("name", ["audio"])[0])
            body = self.read_json()
            route = POST.get(u.path)
            if not route:
                return self.send_bytes(404, b"Not found", "text/plain")
            r = route(self.project, self.job, body)
            self.send_json(*(r if isinstance(r, tuple) else (r,)))
        except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
            pass
        except Exception as e:
            self.send_json({"error": f"{type(e).__name__}: {e}"}, 500)

    def upload(self, name):
        try:
            added = self.project.add_upload(self.rfile, int(self.headers.get("Content-Length") or 0), unquote(name))
        except ValueError as e:
            return self.send_json({"error": str(e)}, 400)
        self.send_json({"added": added})

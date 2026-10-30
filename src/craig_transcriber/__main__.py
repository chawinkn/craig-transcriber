"""Craig Transcriber: run `craig-transcriber` or `python -m craig_transcriber`, see README.md."""

import argparse
import os
import sys
import threading
import webbrowser
from pathlib import Path

os.environ.setdefault("HF_HUB_DISABLE_SYMLINKS_WARNING", "1")

from . import server, transcribe
from .project import Project


def main():
    ap = argparse.ArgumentParser(prog="craig-transcriber", description="Craig Transcriber")
    ap.add_argument("--port", type=int, default=8765)
    ap.add_argument("--host", default="127.0.0.1", help="address to listen on (0.0.0.0 inside a container)")
    ap.add_argument("--data", default="craig_work", help="folder where audio copies and your work are kept")
    ap.add_argument("--no-browser", action="store_true", help="do not open the browser automatically")
    args = ap.parse_args()
    transcribe.add_nvidia_dll_dirs()
    proj = Project(Path(args.data).resolve())
    try:
        httpd = server.make_server(args.host, args.port, proj, transcribe.Job(proj))
    except OSError as e:
        sys.exit(f"Could not start on port {args.port} ({e}). Another copy may be running; try --port {args.port + 1}")
    url = f"http://127.0.0.1:{args.port}"
    print(f"\nCraig Transcriber is running at {url}\nYour work is saved in: {proj.dir}\nPress Ctrl+C to quit.\n")
    if not transcribe.WhisperEngine.available():
        print("NOTE: faster-whisper is not installed yet. Run:  pip install faster-whisper\n")
    if not args.no_browser:
        threading.Timer(0.6, lambda: webbrowser.open(url)).start()
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nBye.")


if __name__ == "__main__":
    main()

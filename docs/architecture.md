# Architecture

Local app that turns a Craig (craig.chat) multi-track recording into a transcript with
faster-whisper, then serves a browser UI to listen Line by Line and fix mistakes. Nothing leaves the
machine. Thai and English (mixed included) come first: the Thai models, Line splitting and joining,
and the review rules are tuned for them; other languages run through auto-detect, untested.
Dependencies: stdlib only, plus `faster-whisper` (which pulls in `av` and `numpy`). Domain terms:
`GLOSSARY.md`; user-facing changes: `CHANGELOG.md`.

Import direction: `project` <- `transcribe` <- `server` <- `__main__`, no cycles. All of it is the
`craig_transcriber` package under `src/` (modules import each other with `from . import`); `main()`
in `__main__.py`, run as `craig-transcriber` or `python -m craig_transcriber`, wires `Project(dir)`,
`Job(proj)` and `server.make_server(host, port, proj, job)`. Tests are one file per module in
`tests/` (`test_project.py`, `test_lines.py`, `test_engine.py`, `test_job.py`, `test_server.py`,
`test_scripts.py`), with the shared helpers and fake engines in `tests/helpers.py`. Dependencies,
entry point and ruff settings are in `pyproject.toml`.

## `project.py`

`Project(data_dir)` owns the state `{speakers, lines, seq}` behind a private RLock; callers never
see the lock or the dict.

- Reads return copies: `state()`, `speaker()`, `audio()`, `export()`.
- Every mutation locks and saves itself to `project.json` (tmp file + `os.replace`): `add_upload`,
  `edit_lines`, `add_line_after`, `add_line_at`, `delete_line`, `rename_speaker`, `remove_speaker`,
  `replace_lines`, `replace_stretch`, `set_speech`, `dismiss_missed`, `reset`.
  - `replace_lines` is the full run: stores the Speaker's `run` record (model, language, detected,
    vocabulary, device, time; built by `Job` from `RunOptions`) and `speech`, clears `dismissed`.
  - `replace_stretch` swaps only the Lines whose midpoint is inside the stretch and keeps run,
    speech and dismissed.
  - Deleting a Speaker's last Line clears their `run`.
  - `reset()` removes only `project.json` and `audio/`, never the data dir.
- Audio copies live in `<dir>/audio/<sid><ext>`. All IDs (`s…`, `l…`) come from one counter, `seq`.
- `add_upload` raises `ValueError` carrying the user-facing message.
- `state()` computes, and stores nothing of it:
  - per Speaker: `touched` (a Line reviewed, retyped against `orig`, or deleted by hand since the
    last run) and `missed` (Missed speech: `speech` minus Line coverage, stretches of at least
    `MISSED_MIN_VOICE`, minus `dismissed`);
  - per Line: `edited`, `mixed`, `unsure_words` (character spans of words under `UNSURE_WORD_PROB`),
    `reasons` and `unsure`. `reasons` can be unsure word, repeated phrase, foreign letters, timing,
    missed speech. Edited Lines have none.
- All review rules live here and run at read time on the current text and times, so a rule change
  applies to old Lines too. `review_flags` combines `unsure_spans`, `repeats`, `foreign_letters`,
  `too_fast` and `too_slow`; `transcribe.py` runs none of them.
- Pure helper functions: `hms`, `srt_time`, `speaker_name_from`, `probe_duration`,
  `missed_stretches`.

## `transcribe.py`

**Models**
- `MODELS` is the one model catalog. `model_catalog(data_dir)` adds `slow`, `default` (cpu/gpu) and
  each Thai model's state from `thai_model_state()`: Installed only when all `MODEL_FILES` exist,
  else incomplete or missing. It is sent to the page in `/api/state` `env.models`.
- `convert_model.py` is a separate optional module, run as
  `python -m craig_transcriber.convert_model` (needs the `convert` extra: `ctranslate2`,
  `transformers`, `torch`) that converts the Thai models into `<data>/models/<name>/`
  (`output_dir()` there uses `transcribe.model_dir()`). It imports `transcribe`; the app never
  imports it.

**`WhisperEngine(model_name, prefer_cpu, on_status)`** is only the Whisper side.
- Loads CUDA float16, then CUDA int8_float16, then CPU int8; `use_cpu()` reloads on the CPU;
  `available()` is static.
- Own PyAV `load_audio`, not faster-whisper's loader.
- `transcribe(path, language, prompt, clip=None)` returns
  `(seconds, iterator of {start, end, text, conf, no_speech, words})`; the detected language is in
  `.language`. A `clip` cuts the audio, padded by `CLIP_PAD`, with times staying absolute.
  `clip_timestamps` is not used because it turns VAD off.
- `voice(path)` returns `[[start, end]]` from faster-whisper's VAD.

**`ProcessEngine`** has the same interface and runs `INNER` (a `WhisperEngine`) in a spawned child
(`_engine_worker`; Pipe messages status, ready, failed, start, seg, end, error, cancel, voice).
- A native crash raises `EngineCrashed` instead of killing the server; a crash while loading on the
  GPU retries on the CPU.
- Segments arrive as a `_SegmentStream`; its `close()` (called by `Job` in a `finally`) cancels and
  drains an unfinished run.

**`Job(project, engine_cls=ProcessEngine)`** holds the rules.
- `start(opts)` validates, then runs a daemon thread (`_thread`). `opts` become
  `RunOptions(model, source, language, prefer_cpu, prompt, check, stretch)`. Modes: full run;
  `check` = voice only; `stretch` = one Speaker's `start`/`end` transcribed again.
- `status()` returns a snapshot (polled at `/api/status`, `elapsed` computed inside); also
  `cancel()` and `running`.
- Per Speaker it collects Lines from `lines_from_segments()` into a local list and calls
  `project.replace_lines` only on success, so a failed or cancelled run keeps that Speaker's
  previous Lines; earlier Speakers stay saved.
- CUDA failure mid-job: `engine.use_cpu()`, then redo that Speaker once. The engine is reused while
  (model, prefer_cpu) is unchanged and dropped if its process crashed.
- Decode options are the `DECODE` constant.
- `add_nvidia_dll_dirs()` and `cuda_count()` are module functions.
- Tests pass a fake `engine_cls` (duck typing; `transcribe(..., clip=None)` and `voice`).

**`lines_from_segments()`** turns segments into Lines:
- drops empty text and segments with no_speech > 0.8 and conf < -1.0;
- splits at word pauses >= 0.6 s (`LINE_GAP`), snapping the cut to a word start or syllable edge,
  cap 12 s (`LINE_MAX`);
- each Line carries `words` [{text, prob}]; split Lines get confidence from word probabilities;
- `_join_fragments` then joins a Line cut inside a Thai word (the next starts with a vowel or mark
  that cannot start a word, or this one ends with a vowel written before its consonant) and a run of
  tiny Lines (<= 3 chars, < 0.6 s apart) with the Line after it, within the 12 s cap.

## `server.py`

- `Handler` (stdlib `BaseHTTPRequestHandler`) reads `self.server.project` and `.job`.
  `make_server()` builds the `ThreadingHTTPServer` on `--host` (default 127.0.0.1; Docker uses
  0.0.0.0).
- `Handler.allowed()` answers 403 to any request whose `Host` is not 127.0.0.1, localhost or [::1]
  (DNS rebinding) and to any POST whose `Origin` differs from `Host` (cross-site).
- JSON API under `/api/*`: state, status, transcribe, cancel, lines, line/add (`after`, or `spk` +
  `start` + `end`), line/delete, missed/dismiss, speaker, speaker/remove, reset, upload. The JSON
  POST routes are one-line delegations in the `POST` dict.
- `/audio/<sid>` has hand-rolled Range support (browser seeking needs it). `/export.{txt,srt,json}`
  downloads the transcript.
- `/api/upload` streams the raw body (name in `?name=`) and accepts audio files or a `.zip` of
  tracks (Craig names them `1-name.flac`; `speaker_name_from` strips the prefix).

## `static/` and `__main__.py`

- `static/` (inside the package, shipped as package data) is the whole frontend: `index.html`
  (markup, at `/`), `app.js`, `style.css`, all served from the `STATIC` map in `server.py`. Each
  file is re-read on every request, so an edit needs only a browser reload. No build step.
- `__main__.py`: argparse, builds `Project` and `Job`, starts the server.

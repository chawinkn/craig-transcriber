<div align="center">

# Craig Transcriber

**Turn a [Craig](https://craig.chat) multi-track Discord recording into an accurate, speaker-labelled transcript, entirely on your own computer.**

![Python](https://img.shields.io/badge/python-3.9%2B-blue)
![Whisper](https://img.shields.io/badge/engine-faster--whisper-green)
![Docker](https://img.shields.io/badge/docker-ready-2496ED)
[![License: MIT](https://img.shields.io/badge/license-MIT-yellow)](LICENSE)

[Overview](#overview) • [Features](#features) • [Getting started](#getting-started) • [Usage](#usage) • [Choosing a model](#choosing-a-model) • [Development](#development) • [Troubleshooting](#troubleshooting)

</div>

## Overview

[Craig](https://craig.chat) records each person in a Discord call on a separate audio track. Craig Transcriber runs [faster-whisper](https://github.com/SYSTRAN/faster-whisper) on each track and merges the results into one transcript in time order. Because every track belongs to one person, each line is labelled with the right speaker, with no diarization guesswork. A browser-based review screen then lets you listen line by line and fix what Whisper got wrong.

> [!NOTE]
> Nothing leaves your machine. Audio, transcripts and models all stay local. This project is not affiliated with Craig or OpenAI.

### Language support

The project currently aims at **Thai and English first**, including Thai speech with English words mixed in. The models, defaults and review rules are tuned and tested for these two:

- The optional Thai models only transcribe Thai.
- How Lines are split and joined is tuned for Thai, which writes no spaces between words.
- The check for made-up text tags any letters that are neither Thai nor Latin as **unsure**.

Other languages Whisper knows can still be transcribed with **Detect automatically**, but they are untested. Languages in other scripts (Japanese, Chinese, Arabic, ...) will have every Line tagged unsure.

## Features

- **Drop in Craig's `.zip`**, or individual audio files (FLAC, WAV, MP3, OGG, Opus, M4A, ...). One track per person.
- **Local transcription**: Whisper models from `small` to `large-v3`. It runs on an NVIDIA GPU (CUDA 12), falls back automatically to the CPU, and is resilient to GPU errors mid-run.
- **Thai and English first**, or auto-detect for other languages (untested, see [Language support](#language-support)). Thai mode handles mixed Thai/English speech best.
- **Spelling hints**: a word list steers how names and technical terms are written.
- **Fast review**:
  - Play any line, change the speed, loop it, or auto-play the next one.
  - `Alt+Enter` marks a line reviewed and plays the next.
  - `Alt+↓` jumps to the next unsure line you have not reviewed.
  - Filter to unreviewed lines, lines worth a second look (unsure and not reviewed yet), or lines mixing Thai and English.
  - Find and replace across the transcript.
- **Safe by default**:
  - Edits save automatically.
  - Re-transcribing a person replaces their lines only after the new run succeeds.
  - Closing the tab with unsaved edits warns you.
- **Export** as `.txt` (`[time] Person: words`), `.srt` subtitles, or `.json`.

## Getting started

You can run it with Docker (simplest, with the `large-v3` model included) or directly with Python.

### Option 1: Docker

Prerequisites:

- [Docker](https://docs.docker.com/get-docker/)
- For GPU acceleration: an NVIDIA driver and the [NVIDIA Container Toolkit](https://docs.nvidia.com/datacenter/cloud-native/container-toolkit/install-guide.html) _(Docker Desktop on Windows/WSL2 already includes GPU support)_

1. Build the image:
   ```bash
   docker build --build-arg GPU=1 -t craig-transcriber .   # omit --build-arg GPU=1 for CPU only
   ```
2. Run it (drop `--gpus all` on a machine without an NVIDIA GPU):
   ```bash
   docker run --init --rm --gpus all -p 127.0.0.1:8765:8765 -v craig_data:/data craig-transcriber
   ```
3. Open http://127.0.0.1:8765.

Your work is stored in the `craig_data` volume and survives rebuilds.

> [!NOTE]
> The image bakes in the `large-v3` model, so the first build downloads about 3 GB and the image is about 6 GB. Other models are downloaded on demand and are discarded when the container exits.

> [!IMPORTANT]
> Keep `127.0.0.1:` in the `-p` flag. The app has no login, so publishing the port on all interfaces lets anyone on your network read and delete your transcripts.

### Option 2: Python

Prerequisites:

- [Python](https://www.python.org/downloads/) 3.9 or later
- For GPU acceleration: an NVIDIA GPU with a driver that supports CUDA 12

1. Create a virtual environment and install the dependencies:
   ```bash
   python3 -m venv .venv
   source .venv/bin/activate        # Windows: .venv\Scripts\activate
   pip install -r requirements.txt
   pip install nvidia-cublas-cu12 "nvidia-cudnn-cu12==9.*"   # optional, for NVIDIA GPUs
   ```
2. Start the app:
   ```bash
   python main.py
   ```

Your browser opens at http://127.0.0.1:8765, and your work is saved in `craig_work/`.

> [!TIP]
> A virtual environment is strongly recommended. The dependencies take several GB, and many Linux distributions refuse system-wide `pip install` with `externally-managed-environment`.

| Flag | Default | Description |
|---|---|---|
| `--port` | `8765` | Port to listen on |
| `--host` | `127.0.0.1` | Address to listen on |
| `--data` | `craig_work` | Folder for audio copies and your work |
| `--no-browser` | | Don't open the browser automatically |

## Usage

The app walks you through four steps:

1. **Add your recording.** Download the multi-track `.zip` from Craig after the call, and drop it on the page. Each person appears with their Discord name, and you can rename them.
2. **Make the transcript.**
   - Pick the language, the quality (model) and the device, then press **Start transcribing**.
   - Optionally, open the hints and list names or terms in the spelling you want.
   - Progress, an estimated time left and the latest lines show live.
3. **Check and fix.**
   - Press ▶ to hear a line, type to correct it, and tick **reviewed** (or press `Alt+Enter` to tick it and move on).
   - Start with the lines tagged **unsure**, using the "worth a second look" filter, and press `Alt+↓` to jump to the next one. The "Thai/English" filter lists the lines tagged **TH/EN**.
     A line is **unsure** when it has a word the model was not confident about (underlined in the text), or when its text looks made up (a phrase repeated over and over, letters that are neither Thai nor Latin, or faster speech than anyone manages), or when a long Line has far too little text for its length (speech the model missed). The tag shows why next to it (the unsure words, repeated phrase, foreign letters, timing or missed speech). Editing the text clears the tag and the underlines, whatever the cause. Lines from older runs have no word confidence, so only the made-up checks apply to them; transcribe the person again to get underlines. **TH/EN** marks Thai with English words in it.
   - A dashed **Missed speech** row marks 2 seconds or more of voice (found on each run) that no line covers. Press ▶ to hear it; `Alt+↓` stops there too. **+ add Line here** adds an empty line with the stretch's times, ready to type into; **dismiss** hides the row until that person is transcribed again. Exports contain only lines.
     A project transcribed before this feature shows **Check for missed speech** above the lines; it finds the voice in seconds without transcribing again and changes no line.
     **transcribe this part again**, on a Missed speech row or a "missed speech" line, transcribes just that stretch with the choices from step 2 and replaces only the lines inside it (it asks first if you edited any); a failed or stopped run changes nothing.
4. **Save your work.** Download the transcript as `.txt`, `.srt` or `.json`.

## Choosing a model

| Model | Download | Notes |
|---|---|---|
| `small` | ~0.5 GB | Default without a GPU; fine on a CPU |
| `medium` | ~1.5 GB | Better; slow on a CPU |
| `large-v3-turbo` | ~1.6 GB | Several times faster than `large-v3`; accuracy varies by language |
| `large-v3` | ~3 GB | Most accurate; default with a GPU; fits in ~6 GB of VRAM |
| `typhoon` | ~6 GB to install, ~3 GB after | Thai only: [Typhoon Whisper Large v3](https://huggingface.co/typhoon-ai/typhoon-whisper-large-v3), tuned for accuracy |
| `pathumma` | ~3 GB | Thai only: [Pathumma Whisper Large v3, noise fine-tuned](https://huggingface.co/PogusTheWhisper/Pathumma-whisper-th-large-v3-natural-noise-finetuned), for casual speech with background noise |

You can also enter any other faster-whisper model name or Hugging Face repository under **Other model name**.

> [!NOTE]
> In a test on one-minute Thai clips, `pathumma` spelled clear speech best, with `typhoon` close behind and `large-v3` last. None of them read noisy speech over game audio well. Both Thai models return about a minute of speech as **one long line**, so reviewing line by line is harder; `large-v3` stays the default for that reason.

### Installing a Thai model

The Thai models are not published in faster-whisper's format, so each one is converted once on your machine. The conversion needs extra packages that the app itself does not:

```bash
pip install ctranslate2 transformers torch
python convert_model.py typhoon     # or: pathumma
```

The model is written to `craig_work/models/<name>/` (use `--data` if you run `main.py` with another folder). Until then, choosing it shows this command and the run will not start. Set **Language spoken** to Thai when you use one. `convert_model.py` also takes any Hugging Face Whisper repository id and prints the folder to enter under **Other model name**.

With Docker, convert on the host, then add the folder to `docker run`:

```bash
docker run --init --rm --gpus all -p 127.0.0.1:8765:8765 -v craig_data:/data -v "$PWD/craig_work/models:/data/work/models:ro" craig-transcriber
```

> [!NOTE]
> Each person's track is transcribed separately and spans the whole recording, though silence is skipped. Total time grows with both the meeting length and the number of people. Without a GPU, the large models take hours for a long meeting.

## Development

```bash
python3 test_app.py   # stdlib unittest; no model or GPU needed
```

| File | Role |
|---|---|
| `main.py` | Entry point: parses arguments, wires everything together, starts the server |
| `project.py` | `Project`: the saved project (speakers, lines, audio copies) and exports |
| `transcribe.py` | `WhisperEngine` (model loading, audio decoding) and `Job` (the background transcription job) |
| `server.py` | HTTP handler: JSON API, audio streaming with Range support, the page |
| `static/index.html` | The whole frontend, with no build step |
| `convert_model.py` | Optional one-time installer for the Thai models; not imported by the app |

`static/index.html` is re-read on every request, so HTML edits need only a browser reload. Python edits need a restart.

With Docker, the source is copied into the image at build time. To iterate without rebuilding, mount it:

```bash
docker run --init --rm -p 127.0.0.1:8765:8765 -v craig_data:/data -v "$PWD:/app" craig-transcriber
```

Rebuild after changing the `Dockerfile` or dependencies. The dependency and model layers are cached, so a source-only rebuild is quick.

## Troubleshooting

- **"No NVIDIA graphics card was found"**:
  - Update your NVIDIA driver, and with Python, install the optional `nvidia-*` packages above.
  - With Docker, build with `--build-arg GPU=1` and run with `--gpus all`.
  - The card must support CUDA 12.
- **The graphics card fails or runs out of memory**: the app switches to the CPU on its own. To stay on the GPU, choose a smaller model such as `large-v3-turbo` or `medium`, and close other GPU-heavy apps.
- **"Could not start on port 8765"**: another copy, or a container, is already using that port. Start with `--port 8766`, or with Docker map `-p 127.0.0.1:8766:8765`.
- **Start over**: use the **Start over** button in the app. Alternatively, delete `craig_work/`, or for Docker run `docker volume rm craig_data`.

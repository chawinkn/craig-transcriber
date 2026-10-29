# Changelog

Notable changes, newest first. There are no numbered releases yet, so entries are grouped by the date they reached `main`.

## 2026-10-29

### Fixed

- Lines no longer come out one character at a time. Some models emit a segment per piece of a word, which showed as dozens of one-character Lines; a run of tiny Lines now joins into one Line with the Line after it, up to 12 s (#18).
- A word cut by a pause no longer stays split across two Lines (for example `ก` / `็คือแบบว่า`): a Line that starts with a Thai vowel or mark that cannot start a word joins the Line before it (#20).

## 2026-10-26

### Added

- Whisper runs in a separate process, so a graphics card crash (seen on a 6 GB laptop GPU with little free memory) no longer stops the app. The run reports the crash, retries on the processor where it can, and cancelling stops the work promptly (#17).
- Each person's saved run also records the vocabulary and the device actually used (#16).

### Changed

- Long Thai Lines are split at pauses in speech, at a word start or syllable edge, and kept under 12 s. The Thai models used to return Lines of up to 50 s (#9).
- The page reads the list of models, their sizes and whether a Thai model is installed from the app instead of keeping its own copy. A Thai model counts as installed only when all its files are there (#15).
- The unsure, TH/EN and edited tags on each Line come from the app, so the page and the filters always agree (#14).

### Fixed

- The time-left estimate is right for runs with several people (#16).
- Converting a Thai model writes `preprocessor_config.json`, which newer `transformers` versions left out (#8).
- Removed a decoding option that dropped about 70% of real speech on noisy Thai audio (#8).

## 2026-10-25

### Added

- Optional Thai models, Typhoon and Pathumma, installed with `convert_model.py` (#6).
- Every person is ticked for transcription right after upload (#6).
- Lines whose text looks made up (repeated phrases, letters that are neither Thai nor Latin, impossibly fast speech) are tagged unsure (#7).
- Each person keeps the model, language and time of the run that made their Lines, and the People list shows it (#7).
- Starting a run asks first when a person's Lines were corrected or deleted by hand, not only when they were reviewed (#7).
- Decoding blocks long repeat loops, and the vocabulary hints are also sent as hotwords (#7).

### Fixed

- The made-up text check no longer flags real speech such as `ไม่ไม่ไม่ไม่`, `555555` or Vietnamese, and the unsure tag it sets clears once you correct the text (#7).

## 2026-10-11

### Added

- First version: upload a Craig multi-track recording, transcribe each person locally with faster-whisper, then listen line by line in the browser, correct the text and export `.txt`, `.srt` or `.json`.
- Docker image with the large-v3 model built in, and optional NVIDIA GPU support.

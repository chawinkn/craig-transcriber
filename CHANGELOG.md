# craig-transcriber

## 0.3.1

### Patch Changes

- [#18](https://github.com/chawinkn/craig-transcriber/pull/18) [`5e743a7`](https://github.com/chawinkn/craig-transcriber/commit/5e743a7d5cf2cc15f57895501a3eded219f69003) Thanks [@chawinkn](https://github.com/chawinkn)! - Lines no longer come out one character at a time. Some models (seen with Pathumma on a noisy recording) emit a segment per piece of a word, which showed as dozens of one-character Lines; a run of tiny Lines (3 characters or fewer, under 0.6 s apart) now joins into one Line with the Line after it, up to 12 s ([#19](https://github.com/chawinkn/craig-transcriber/issues/19)).

- [#20](https://github.com/chawinkn/craig-transcriber/pull/20) [`f56328f`](https://github.com/chawinkn/craig-transcriber/commit/f56328fd4ce4914c52a167f6f667ee1c18c5ed35) Thanks [@chawinkn](https://github.com/chawinkn)! - A word cut by a pause no longer stays split across two Lines (for example `ก` / `็คือแบบว่า`): a Line that starts with a Thai vowel or mark that cannot start a word, or follows one ending in a vowel written before its consonant, joins the Line before it. Existing Lines change only when you transcribe that person again.

## 0.3.0

### Minor Changes

- [#17](https://github.com/chawinkn/craig-transcriber/pull/17) [`5454251`](https://github.com/chawinkn/craig-transcriber/commit/54542512325981374fd6dd149687cea8919a86aa) Thanks [@chawinkn](https://github.com/chawinkn)! - Whisper runs in a separate process, so a graphics card crash (seen on a 6 GB laptop GPU with little free memory) no longer stops the app. The run reports the crash and retries that person on the processor where it can, and cancelling stops the work promptly ([#13](https://github.com/chawinkn/craig-transcriber/issues/13)).

- [#9](https://github.com/chawinkn/craig-transcriber/pull/9) [`b2c6470`](https://github.com/chawinkn/craig-transcriber/commit/b2c6470f5dd0105aeed94576d6687b47be019662) Thanks [@chawinkn](https://github.com/chawinkn)! - Long Lines are split at pauses in speech, cutting at a word start or a Thai syllable edge, and kept under 12 s. The Thai models used to return Lines of up to 50 s.

### Patch Changes

- [#17](https://github.com/chawinkn/craig-transcriber/pull/17) [`cec4f43`](https://github.com/chawinkn/craig-transcriber/commit/cec4f4300062c7a49ef169ba7239625bf97befdf) Thanks [@chawinkn](https://github.com/chawinkn)! - After a crash the next run starts a fresh engine instead of reusing the dead one, and cancelling can no longer stop the wrong run.

- [#16](https://github.com/chawinkn/craig-transcriber/pull/16) [`d1ffaae`](https://github.com/chawinkn/craig-transcriber/commit/d1ffaaea0147673e7baec17a8a8b666f34a7b43b) Thanks [@chawinkn](https://github.com/chawinkn)! - Each person's saved run also records the vocabulary and the device actually used, and the time-left estimate is right for runs with several people ([#12](https://github.com/chawinkn/craig-transcriber/issues/12)).

- [#15](https://github.com/chawinkn/craig-transcriber/pull/15) [`2262c20`](https://github.com/chawinkn/craig-transcriber/commit/2262c208408d39f6c1a786d77ea49f21b443ec9f) Thanks [@chawinkn](https://github.com/chawinkn)! - The page reads the models, their sizes and whether each Thai model is installed from the app instead of keeping its own copy. A Thai model counts as installed only when all its files are there ([#11](https://github.com/chawinkn/craig-transcriber/issues/11)).

- [#14](https://github.com/chawinkn/craig-transcriber/pull/14) [`6ba8f44`](https://github.com/chawinkn/craig-transcriber/commit/6ba8f44cacda191d364693b7c758beff327b4f00) Thanks [@chawinkn](https://github.com/chawinkn)! - The unsure, TH/EN and edited tags on each Line come from the app, so the page and its filters always agree. Lines typed in by hand count as edited ([#10](https://github.com/chawinkn/craig-transcriber/issues/10)).

- [#8](https://github.com/chawinkn/craig-transcriber/pull/8) [`e6bdac7`](https://github.com/chawinkn/craig-transcriber/commit/e6bdac748f59a528b443a2b8b8a624f2c1a73ada) Thanks [@chawinkn](https://github.com/chawinkn)! - Converting a Thai model writes `preprocessor_config.json`, which newer `transformers` versions left out, so faster-whisper can load it. Re-run `python convert_model.py <name>` for a model converted before this.

- [#8](https://github.com/chawinkn/craig-transcriber/pull/8) [`5263f47`](https://github.com/chawinkn/craig-transcriber/commit/5263f4796e1fc4d021a858b88aa580312aabe179) Thanks [@chawinkn](https://github.com/chawinkn)! - Removed the silence-hallucination skip from decoding: on noisy Thai audio it dropped about 70% of real speech ([#4](https://github.com/chawinkn/craig-transcriber/issues/4), [#5](https://github.com/chawinkn/craig-transcriber/issues/5)).

## 0.2.0

### Minor Changes

- [#6](https://github.com/chawinkn/craig-transcriber/pull/6) [`3cc2903`](https://github.com/chawinkn/craig-transcriber/commit/3cc2903b2fd3c1632bc38d67d05976171b9afebf) Thanks [@chawinkn](https://github.com/chawinkn)! - Add the optional Thai models Typhoon and Pathumma. Install one with `python convert_model.py typhoon` (or `pathumma`), then choose it on the page; for mixed Thai and English speech, Pathumma does best.

- [#7](https://github.com/chawinkn/craig-transcriber/pull/7) [`4c3e147`](https://github.com/chawinkn/craig-transcriber/commit/4c3e147ddb2218dafe9ec912224a1e31d13565c0) Thanks [@chawinkn](https://github.com/chawinkn)! - Each person keeps the model, language and time of the run that made their Lines, and the People list shows it ([#1](https://github.com/chawinkn/craig-transcriber/issues/1)). Starting a run asks first when a person's Lines were corrected by hand, not only reviewed ([#2](https://github.com/chawinkn/craig-transcriber/issues/2)). Lines whose text looks made up (a repeated phrase, letters that are neither Thai nor Latin) are tagged unsure ([#3](https://github.com/chawinkn/craig-transcriber/issues/3)). Decoding blocks long repeat loops, and the vocabulary hints are also sent as hotwords ([#4](https://github.com/chawinkn/craig-transcriber/issues/4)).

### Patch Changes

- [#6](https://github.com/chawinkn/craig-transcriber/pull/6) [`61180c3`](https://github.com/chawinkn/craig-transcriber/commit/61180c3df3285f0ed60427a841eabd46abd37b46) Thanks [@chawinkn](https://github.com/chawinkn)! - Every person is ticked for transcription right after upload.

- [#7](https://github.com/chawinkn/craig-transcriber/pull/7) [`67999c4`](https://github.com/chawinkn/craig-transcriber/commit/67999c45f0f59645a197eba38e4fab277d83563b) Thanks [@chawinkn](https://github.com/chawinkn)! - The made-up text check no longer flags real speech such as `ไม่ไม่ไม่ไม่`, `555555` or Vietnamese, and its unsure tag clears once you correct the text. Deleting a Line by hand counts as touching that person, so the next run asks first.

## 0.1.0

### Minor Changes

- [`3b81b9d`](https://github.com/chawinkn/craig-transcriber/commit/3b81b9d7093360eadf222dcdea155eb27ab8a9f4) Thanks [@chawinkn](https://github.com/chawinkn)! - First version: upload a Craig multi-track recording, transcribe each person locally with faster-whisper, then listen Line by Line in the browser, correct the text and export `.txt`, `.srt` or `.json`.

- [`93e4a58`](https://github.com/chawinkn/craig-transcriber/commit/93e4a5820b17b80f996f849c08a7b797ccddc885) Thanks [@chawinkn](https://github.com/chawinkn)! - Docker image with the large-v3 model built in, and optional NVIDIA GPU support (`--build-arg GPU=1`).

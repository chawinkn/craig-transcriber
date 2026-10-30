# craig-transcriber

## 0.6.1

### Patch Changes

- [#43](https://github.com/chawinkn/craig-transcriber/pull/43) [`dcc601a`](https://github.com/chawinkn/craig-transcriber/commit/dcc601a1409af0de9f4fe0d9e536a8b69e6481cb) Thanks [@chawinkn](https://github.com/chawinkn)! - The "Download subtitles (.srt)" and "Download data (.json)" buttons use the page's text colour instead of dark-blue link text.

## 0.6.0

### Minor Changes

- [#40](https://github.com/chawinkn/craig-transcriber/pull/40) [`84c2206`](https://github.com/chawinkn/craig-transcriber/commit/84c22067b4904c4b9b82831e092451fe263d80f9) Thanks [@chawinkn](https://github.com/chawinkn)! - The app is now an installable package. Install it with `pip install .` (add `.[gpu]` for NVIDIA, `.[convert]` for converting Thai models), run it with `craig-transcriber` or `python -m craig_transcriber`, and convert a Thai model with `python -m craig_transcriber.convert_model pathumma`. `python main.py` and `python convert_model.py` no longer exist; the Docker image is used the same way as before.

## 0.5.1

### Patch Changes

- [#38](https://github.com/chawinkn/craig-transcriber/pull/38) [`95719ce`](https://github.com/chawinkn/craig-transcriber/commit/95719ce9c2460ace519cc413ac0be0039de9de52) Thanks [@chawinkn](https://github.com/chawinkn)! - A Line is judged by the current rules every time it is shown, so a rule change reaches Lines from older runs too. The "looks made up" tag that old runs left on correct Lines (for example "กี่หน้ากี่หน้ากี่หน้า" or "ขอบคุณครับ" in 0.1 s) is gone.

## 0.5.0

### Minor Changes

- [#37](https://github.com/chawinkn/craig-transcriber/pull/37) [`e9f1122`](https://github.com/chawinkn/craig-transcriber/commit/e9f1122b77f98723035eac93ba797bd96e902d5b) Thanks [@chawinkn](https://github.com/chawinkn)! - Each run also records where there is voice, and stretches of 2 s or more with voice but no Line show as **Missed speech** rows between the Lines, with ▶, in "worth a second look" and reached by `Alt+↓` ([#33](https://github.com/chawinkn/craig-transcriber/issues/33)).

- [#37](https://github.com/chawinkn/craig-transcriber/pull/37) [`8579daf`](https://github.com/chawinkn/craig-transcriber/commit/8579daf52083366010cebb0f510dc3226f0433d9) Thanks [@chawinkn](https://github.com/chawinkn)! - "Transcribe this part again" on a Missed speech row or a "missed speech" Line re-runs only that stretch with the step 2 settings and replaces only the Lines inside it; every other Line, tick and edit stays ([#36](https://github.com/chawinkn/craig-transcriber/issues/36)).

### Patch Changes

- [#37](https://github.com/chawinkn/craig-transcriber/pull/37) [`71b34a0`](https://github.com/chawinkn/craig-transcriber/commit/71b34a006147173dffe509f72933fea8150a32a6) Thanks [@chawinkn](https://github.com/chawinkn)! - A Line of 4 s or more with under 2 characters per second is tagged unsure with the reason "missed speech": the model swallowed what was said there ([#32](https://github.com/chawinkn/craig-transcriber/issues/32)).

- [#37](https://github.com/chawinkn/craig-transcriber/pull/37) [`cdde2cd`](https://github.com/chawinkn/craig-transcriber/commit/cdde2cd8b44471ca3e0be7b0d7d312e4d4df999d) Thanks [@chawinkn](https://github.com/chawinkn)! - A Missed speech row can be dismissed (it stays hidden until the next full run) or filled with "+ add line here" ([#34](https://github.com/chawinkn/craig-transcriber/issues/34)).

- [#37](https://github.com/chawinkn/craig-transcriber/pull/37) [`469646e`](https://github.com/chawinkn/craig-transcriber/commit/469646e1ff439252d47557902f494f4ddab35c9c) Thanks [@chawinkn](https://github.com/chawinkn)! - "Check for missed speech" finds Missed speech in projects transcribed before voice was recorded, without touching any Line, tick or edit ([#35](https://github.com/chawinkn/craig-transcriber/issues/35), [#23](https://github.com/chawinkn/craig-transcriber/issues/23)).

## 0.4.0

### Minor Changes

- [#30](https://github.com/chawinkn/craig-transcriber/pull/30) [`8ca7bbe`](https://github.com/chawinkn/craig-transcriber/commit/8ca7bbea767140eea4fb4b2bd517c83c0d758505) Thanks [@chawinkn](https://github.com/chawinkn)! - Words the model was not confident about (**Unsure words**) are underlined in the Line's text, and a Line with one is tagged unsure ([#26](https://github.com/chawinkn/craig-transcriber/issues/26)).

- [#30](https://github.com/chawinkn/craig-transcriber/pull/30) [`580cdcc`](https://github.com/chawinkn/craig-transcriber/commit/580cdcc70400c731160593fd5f1771d25289ecba) Thanks [@chawinkn](https://github.com/chawinkn)! - The unsure tag says why: "unsure word: ดองครีม", "repeated phrase", "foreign letters" or "timing". Editing a Line's text clears the tag, its reasons and its underlines ([#28](https://github.com/chawinkn/craig-transcriber/issues/28)).

- [#30](https://github.com/chawinkn/craig-transcriber/pull/30) [`0b8ca18`](https://github.com/chawinkn/craig-transcriber/commit/0b8ca1837e5967922bf09517725eeda6ab29603f) Thanks [@chawinkn](https://github.com/chawinkn)! - "Worth a second look" lists unsure Lines not yet reviewed, Thai/English Lines get their own filter, and `Alt+↓` jumps to the next unsure Line ([#27](https://github.com/chawinkn/craig-transcriber/issues/27)).

### Patch Changes

- [#31](https://github.com/chawinkn/craig-transcriber/pull/31) [`1d1cd66`](https://github.com/chawinkn/craig-transcriber/commit/1d1cd66fc7acfef1c05c488120d732ef6ce66e6f) Thanks [@chawinkn](https://github.com/chawinkn)! - The Unsure word cutoff is 0.3, set from 219 reviewed Lines of a Thai meeting: it tags 12% of Lines and catches 6 of 17 wrong ones, where the old tag caught none. The Line-level confidence rule, which caught nothing extra, is removed ([#29](https://github.com/chawinkn/craig-transcriber/issues/29), [#24](https://github.com/chawinkn/craig-transcriber/issues/24), [#22](https://github.com/chawinkn/craig-transcriber/issues/22)).

- [#30](https://github.com/chawinkn/craig-transcriber/pull/30) [`e7e7be8`](https://github.com/chawinkn/craig-transcriber/commit/e7e7be84afc650091864fba4b50ac31c9d00b72d) Thanks [@chawinkn](https://github.com/chawinkn)! - Real repetition ("กี่หน้ากี่หน้ากี่หน้า") and short Lines with odd timing ("ขอบคุณครับ" in 0.1 s) are no longer tagged as made up: a phrase must repeat 4 times, and the too-fast check needs 20+ characters ([#25](https://github.com/chawinkn/craig-transcriber/issues/25)).

- [#30](https://github.com/chawinkn/craig-transcriber/pull/30) [`dac9991`](https://github.com/chawinkn/craig-transcriber/commit/dac99910b88a1884942db170270de7a5c317032c) Thanks [@chawinkn](https://github.com/chawinkn)! - Thai word pieces that touch are underlined and named as one Unsure word ("ดองครีม", not "ดอง, ครีม").

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

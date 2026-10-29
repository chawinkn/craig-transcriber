# Craig Transcriber

Turns a multi-track Craig recording into a reviewed, per-speaker transcript, entirely on the user's machine.

## Language

**Speaker**:
One participant in a recording, together with their own audio track and the lines transcribed from it.
_Avoid_: Person, participant, track (as the name of the concept)

**Line**:
One short stretch of a Speaker's speech, with its start and end time and its text, that the user listens to and corrects on its own.
_Avoid_: Segment (that is the model's raw output, which may cover many Lines), sentence, utterance

**Unsure** (of a Line):
Tagged for a second look, with the reason shown: the Line has an Unsure word, or its text looks made up (a phrase repeated over and over, letters that are neither Thai nor Latin, or far more text than its time allows). A Line stops being unsure once the user edits its text.
_Avoid_: Suspect (the stored flag behind the made-up causes)

**Unsure word**:
A word in a Line that the model was not confident about, underlined so the user checks it first.
_Avoid_: Weak word, low-probability word

**Missed speech**:
A stretch of a Speaker's audio where someone spoke but no Line holds the words: either no Line covers it, or a Line covers it with far too little text for its length.
_Avoid_: Gap (that also means real silence between Lines), dropped Line

**Thai model**:
A Whisper model fine-tuned to transcribe Thai only, offered as an optional alternative to the general Whisper models.
_Avoid_: Fine-tuned model, custom model

**Installed** (of a Thai model):
Present on this machine and ready to use; a Thai model that is not installed cannot be chosen for a transcription run.
_Avoid_: Downloaded, converted

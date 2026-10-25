# Craig Transcriber

Turns a multi-track Craig recording into a reviewed, per-speaker transcript, entirely on the user's machine.

## Language

**Speaker**:
One participant in a recording, together with their own audio track and the lines transcribed from it.
_Avoid_: Person, participant, track (as the name of the concept)

**Line**:
One short stretch of a Speaker's speech, with its start and end time and its text, that the user listens to and corrects on its own.
_Avoid_: Segment (that is the model's raw output, which may cover many Lines), sentence, utterance

**Thai model**:
A Whisper model fine-tuned to transcribe Thai only, offered as an optional alternative to the general Whisper models.
_Avoid_: Fine-tuned model, custom model

**Installed** (of a Thai model):
Present on this machine and ready to use; a Thai model that is not installed cannot be chosen for a transcription run.
_Avoid_: Downloaded, converted

"""Install a Thai model (or any Hugging Face Whisper model) for faster-whisper.

Run: python -m craig_transcriber.convert_model <model> [--data DIR]
Needs extra packages the app itself does not: pip install ".[convert]"
"""

import argparse
from pathlib import Path

from .transcribe import THAI_MODELS, model_dir


def output_dir(model, data):
    """Where a converted model goes: a Thai model's own folder, or one named after any other repo."""
    return model_dir(Path(data).resolve(), model if model in THAI_MODELS else model.replace("/", "--"))


def main():
    ap = argparse.ArgumentParser(
        prog="python -m craig_transcriber.convert_model",
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    ap.add_argument("model", help=f"{' or '.join(THAI_MODELS)}, or any Hugging Face Whisper repo id")
    ap.add_argument("--data", default="craig_work", help="the same --data folder you give craig-transcriber")
    args = ap.parse_args()

    repo = THAI_MODELS.get(args.model, args.model)
    out = output_dir(args.model, args.data)
    from ctranslate2.converters import TransformersConverter
    from transformers import WhisperProcessor

    print(f"Downloading {repo} and converting it to {out} (several GB, this takes a while)…")
    TransformersConverter(repo, load_as_float16=True, low_cpu_mem_usage=True).convert(
        str(out), quantization="float16", force=True
    )
    # faster-whisper needs tokenizer.json and preprocessor_config.json (128 mel bins); not every repo ships both,
    # and transformers 5 folds the latter into processor_config.json when saving the processor as a whole.
    processor = WhisperProcessor.from_pretrained(repo)
    processor.tokenizer.save_pretrained(str(out))
    processor.feature_extractor.save_pretrained(str(out))
    if args.model in THAI_MODELS:
        print(f"Done. Reload the app and choose the {args.model} model.")
    else:
        print(f"Done. In the app, enter this under Other model name: {out}")


if __name__ == "__main__":
    main()

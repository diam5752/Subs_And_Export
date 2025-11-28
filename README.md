# Greek Sub Publisher

Local-first tooling to normalize vertical videos, transcribe Greek audio with faster-whisper, burn styled subtitles (ASS), and generate social copy.

## Requirements
- Python 3.11+
- ffmpeg available on PATH
- Optional for LLM copy: `OPENAI_API_KEY` and `pip install openai`

Install deps:
```bash
python -m pip install --upgrade pip
pip install -r requirements.txt
```

## Usage
```bash
python -m greek_sub_publisher.cli INPUT.mp4 --output OUTPUT.mp4 --artifacts ./artifacts \
  --model medium --language el --beam-size 5 --best-of 1
```
Add `--llm-social-copy` (and optionally `--llm-model`, `--llm-temperature`) to draft social copy via an OpenAI-compatible LLM.

Artifacts directory will contain WAV/SRT/ASS/transcript and social_copy files.

## Tests
- Fast suite (CI default): `pytest -m "not slow"`
- Full suite (includes regression on `tests/data/demo.mp4` and Whisper run): `pytest`
- LLM path is tested with stubs; no network required.

## CI
GitHub Actions workflow `.github/workflows/tests.yml` installs deps and runs `pytest -m "not slow"` to avoid downloading large Whisper models. Run the full suite locally before releases.***

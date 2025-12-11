"""Configuration constants for the Greek subtitle publisher."""

from pathlib import Path

DEFAULT_WIDTH = 1080
DEFAULT_HEIGHT = 1920
DEFAULT_FPS = 30

DEFAULT_SUB_FONT = "Arial Black"
DEFAULT_SUB_FONT_SIZE = 62  # ~15% larger for better readability on vertical video
DEFAULT_SUB_COLOR = "&H0000FFFF"  # highlight (yellow) in ASS ARGB BGR
DEFAULT_SUB_SECONDARY_COLOR = "&H00FFFFFF"  # base white
DEFAULT_SUB_OUTLINE_COLOR = "&H7F000000"
DEFAULT_SUB_BACK_COLOR = "&H96000000"
DEFAULT_SUB_STROKE_WIDTH = 3
DEFAULT_SUB_ALIGNMENT = 2  # bottom center
DEFAULT_SUB_MARGIN_V = 320  # lift higher to avoid UI chrome
DEFAULT_SUB_MARGIN_L = 80  # ~7.5% margin for safe text area on vertical video
DEFAULT_SUB_MARGIN_R = 80  # ~7.5% margin for safe text area on vertical video
MAX_SUB_LINE_CHARS = 32  # Safe width for Greek uppercase text without edge cutoff

DEFAULT_OUTPUT_SUFFIX = "_subbed"

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent.parent  # /backend/app/core -> project root

# Whisper / STT defaults
WHISPER_MODEL_TURBO = "deepdml/faster-whisper-large-v3-turbo-ct2"  # Main local model for accurate Greek
WHISPER_LANGUAGE = "el"
WHISPER_DEVICE = "auto"  # "cpu", "cuda", "auto"
WHISPER_COMPUTE_TYPE = "auto"  # Let CTranslate2 choose optimal type
WHISPER_CHUNK_LENGTH = 90  # seconds; testing shows 90s is faster than 30s for this hardware
WHISPER_BATCH_SIZE = 16  # batch size for faster-whisper processing

# Hosted STT (OpenAI)
OPENAI_TRANSCRIBE_MODEL = "gpt-4o-mini-transcribe"

# Cloud providers
GROQ_TRANSCRIBE_MODEL = "whisper-large-v3"  # ~200x realtime for Greek

# whisper.cpp / pywhispercpp settings (Metal optimized for Apple Silicon)
WHISPERCPP_MODEL = "large-v3-turbo"  # Best speed/quality balance for Apple Silicon
WHISPERCPP_LANGUAGE = "el"  # Greek default


# LLM social copy defaults (OpenAI API)
SOCIAL_LLM_MODEL = "gpt-4o-mini"

# Audio extraction settings
AUDIO_SAMPLE_RATE = 16000
AUDIO_CHANNELS = 1
AUDIO_CODEC = "pcm_s16le"

# Encoding defaults for delivery to TikTok / Reels / Shorts
DEFAULT_VIDEO_CRF = 16  # lower is higher quality
DEFAULT_VIDEO_PRESET = "medium"  # balanced speed/quality - platforms re-encode anyway
DEFAULT_AUDIO_BITRATE = "256k"
DEFAULT_HIGHLIGHT_COLOR = "&H0000FFFF"  # vivid yellow for per-word fill
USE_HW_ACCEL = True  # Use VideoToolbox on macOS by default

"""Configuration constants for the Greek subtitle publisher."""

from pathlib import Path

DEFAULT_WIDTH = 1080
DEFAULT_HEIGHT = 1920
DEFAULT_FPS = 30

DEFAULT_SUB_FONT = "Arial Black"
DEFAULT_SUB_FONT_SIZE = 58
DEFAULT_SUB_COLOR = "&H0000FFFF"  # highlight (yellow) in ASS ARGB BGR
DEFAULT_SUB_SECONDARY_COLOR = "&H00FFFFFF"  # base white
DEFAULT_SUB_OUTLINE_COLOR = "&H7F000000"
DEFAULT_SUB_BACK_COLOR = "&H96000000"
DEFAULT_SUB_STROKE_WIDTH = 3
DEFAULT_SUB_ALIGNMENT = 2  # bottom center
DEFAULT_SUB_MARGIN_V = 260  # lift a bit higher from bottom
DEFAULT_SUB_MARGIN_L = 220
DEFAULT_SUB_MARGIN_R = 220
MAX_SUB_LINE_CHARS = 14

DEFAULT_OUTPUT_SUFFIX = "_subbed"

PROJECT_ROOT = Path(__file__).resolve().parent

# Whisper / STT defaults
WHISPER_MODEL_SIZE = "tiny"  # Optimized for speed (3-5x faster than medium)
WHISPER_MODEL_TURBO = "deepdml/faster-whisper-large-v3-turbo-ct2"  # Multilingual Turbo model
WHISPER_LANGUAGE = "el"
WHISPER_DEVICE = "auto"  # "cpu", "cuda", "auto"
WHISPER_COMPUTE_TYPE = "int8"  # Force int8 for 2-4x speedup on CPU vs float32

# LLM social copy defaults (OpenAI API)
SOCIAL_LLM_MODEL = "gpt-4o-mini"

# Audio extraction settings
AUDIO_SAMPLE_RATE = 16000
AUDIO_CHANNELS = 1
AUDIO_CODEC = "pcm_s16le"

# Encoding defaults for delivery to TikTok / Reels / Shorts
DEFAULT_VIDEO_CRF = 16  # lower is higher quality
DEFAULT_VIDEO_PRESET = "slow"  # slower preset -> better quality at same bitrate
DEFAULT_AUDIO_BITRATE = "256k"
DEFAULT_HIGHLIGHT_COLOR = "&H0000FFFF"  # vivid yellow for per-word fill
USE_HW_ACCEL = True  # Use VideoToolbox on macOS by default

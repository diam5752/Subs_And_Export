"""Configuration constants for the Greek subtitle publisher."""

from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent.parent  # /backend/app/core -> project root

DEFAULT_WIDTH = 1080
DEFAULT_HEIGHT = 1920
DEFAULT_FPS = 30
MAX_RESOLUTION_DIMENSION = 4096  # Max 4K DCI width/height to prevent DoS
MAX_VIDEO_DURATION_SECONDS = 210  # Max 3.5 minutes to prevent resource exhaustion
MAX_CONCURRENT_JOBS = 2  # Max concurrent processing jobs per user
WATERMARK_PATH = PROJECT_ROOT / "Ascentia_Logo.png"

DEFAULT_SUB_FONT = "Arial Black"
DEFAULT_SUB_FONT_SIZE = 62  # Default tuned for 1080x1920 safe area
# KARAOKE COLORS: Words fill from Secondary → Primary as each \k duration completes
# For word-by-word highlighting: words start white and fill to yellow when spoken
DEFAULT_SUB_COLOR = "&H0000FFFF"  # Primary: Yellow (word becomes this color when spoken)
DEFAULT_SUB_SECONDARY_COLOR = "&H00FFFFFF"  # Secondary: White (word starts this color)
DEFAULT_SUB_OUTLINE_COLOR = "&H7F000000"
DEFAULT_SUB_BACK_COLOR = "&H96000000"
DEFAULT_SUB_STROKE_WIDTH = 3
DEFAULT_SUB_ALIGNMENT = 2  # bottom center
DEFAULT_SUB_MARGIN_V = 320  # lift higher to avoid UI chrome
DEFAULT_SUB_MARGIN_L = 80  # ~7.5% margin for safe text area on vertical video
DEFAULT_SUB_MARGIN_R = 80  # ~7.5% margin for safe text area on vertical video
MAX_SUB_LINE_CHARS = 28  # Safe width for Greek uppercase text without edge cutoff

DEFAULT_OUTPUT_SUFFIX = "_subbed"

# Whisper / STT defaults
WHISPER_MODEL = "medium"  # Optimized for CPU usage (Docker/Mac)

WHISPER_LANGUAGE = "el"
WHISPER_DEVICE = "auto"  # "cpu", "cuda", "auto"
WHISPER_COMPUTE_TYPE = "auto"  # Let CTranslate2 choose optimal type
WHISPER_CHUNK_LENGTH = 90  # seconds; testing shows 90s is faster than 30s for this hardware
WHISPER_BATCH_SIZE = 16  # batch size for faster-whisper processing

# Hosted STT (OpenAI)
OPENAI_TRANSCRIBE_MODEL = "whisper-1"


# Cloud providers
GROQ_TRANSCRIBE_MODEL = "whisper-large-v3"  # ~200x realtime for Greek
GROQ_MODEL_ENHANCED = "whisper-large-v3-turbo"
GROQ_MODEL_ULTIMATE = "whisper-large-v3"
GROQ_MODEL_STANDARD = GROQ_MODEL_ENHANCED

# whisper.cpp / pywhispercpp settings (Metal optimized for Apple Silicon)
WHISPERCPP_MODEL = "medium"  # Optimized for CPU usage (Docker/Mac)
WHISPERCPP_LANGUAGE = "el"  # Greek default


# LLM social copy defaults (OpenAI API)
SOCIAL_LLM_MODEL = "gpt-5.1-mini"
FACTCHECK_LLM_MODEL = "gpt-5.1-mini"
EXTRACTION_LLM_MODEL = "gpt-5.1-mini"

# Tiered LLM defaults
SOCIAL_LLM_MODEL_STANDARD = "gpt-5.1-mini"
SOCIAL_LLM_MODEL_PRO = "gpt-5.1-mini"
FACTCHECK_LLM_MODEL_STANDARD = "gpt-5.1-mini"
FACTCHECK_LLM_MODEL_PRO = "gpt-5.1-mini"
EXTRACTION_LLM_MODEL_STANDARD = "gpt-5.1-mini"
EXTRACTION_LLM_MODEL_PRO = "gpt-5.1-mini"

# Tiered transcription defaults
DEFAULT_TRANSCRIBE_TIER = "standard"
TRANSCRIBE_TIERS = {"standard", "pro"}
TRANSCRIBE_TIER_PROVIDER = {
    "standard": "groq",
    "pro": "groq",
}
TRANSCRIBE_TIER_MODEL = {
    "standard": GROQ_MODEL_STANDARD,
    "pro": GROQ_MODEL_ULTIMATE,
}

# Cost Optimization & Safety Limits
MAX_LLM_INPUT_CHARS = 15000  # Approx 3-4k tokens. Truncate very long transcripts to save cost.
MAX_LLM_OUTPUT_TOKENS_SOCIAL = 3000  # Increased to prevent 'length' finish reason on reasoning models
MAX_LLM_OUTPUT_TOKENS_FACTCHECK = 6000  # Increased for detailed reports + reasoning overhead

# Estimated Pricing per 1M tokens (USD)
# Updates as of late 2025
MODEL_PRICING = {
    "gpt-4o": {"input": 5.00, "output": 15.00},
    "gpt-4o-mini": {"input": 0.15, "output": 0.60},
    "gpt-5.1-mini": {"input": 0.25, "output": 2.00},
    "gpt-5-mini": {"input": 0.25, "output": 2.00},
    "default": {"input": 2.50, "output": 10.00} # Fallback to standard GPT-4 class
}

# Credits pricing (1 credit == pricing unit, not USD)
LLM_TOKEN_CHAR_RATIO = 4.0

CREDITS_PER_1K_TOKENS = {
    "standard": 2,
    "pro": 7,
}
CREDITS_PER_MINUTE_TRANSCRIBE = {
    "standard": 10,
    "pro": 20,
}
CREDITS_MIN_TRANSCRIBE = {
    "standard": 25,
    "pro": 50,
}
CREDITS_MIN_SOCIAL_COPY = {
    "standard": 10,
    "pro": 20,
}
CREDITS_MIN_FACT_CHECK = {
    "standard": 20,
    "pro": 40,
}

# STT pricing (USD per minute). Update with current provider rates.
STT_PRICE_PER_MINUTE_USD = {
    "standard": 0.003,
    "pro": 0.006,
}

# Audio extraction settings
AUDIO_SAMPLE_RATE = 16000
AUDIO_CHANNELS = 1
AUDIO_CODEC = "pcm_s16le"

# Encoding defaults for delivery to social media platforms
DEFAULT_VIDEO_CRF = 23  # balanced quality/size - platforms re-encode anyway
DEFAULT_VIDEO_PRESET = "veryfast"  # Fast encoding - platforms re-encode anyway
DEFAULT_AUDIO_BITRATE = "256k"
DEFAULT_HIGHLIGHT_COLOR = "&H0000FFFF"  # vivid yellow for per-word fill
USE_HW_ACCEL = True  # Use VideoToolbox on macOS by default

# Rate limiting configuration
SIGNUP_LIMIT_PER_IP_PER_DAY = 5  # Max signups per IP per 24 hours
STATIC_RATE_LIMIT = 60  # Max static file requests per minute
STATIC_RATE_LIMIT_WINDOW = 60  # Window in seconds

import functools
import re
import unicodedata
from pathlib import Path
from typing import Iterable, List, Tuple

# Type alias for TimeRange
TimeRange = Tuple[float, float, str]

@functools.lru_cache(maxsize=4096)
def normalize_text(text: str) -> str:
    """
    Uppercase + strip accents for consistent, bold subtitle styling.
    """
    normalized = unicodedata.normalize("NFD", text)
    stripped = "".join(ch for ch in normalized if not unicodedata.combining(ch))
    return stripped.upper()

def format_timestamp(seconds: float) -> str:
    hours = int(seconds // 3600)
    minutes = int((seconds % 3600) // 60)
    secs = seconds % 60
    return f"{hours:01d}:{minutes:02d}:{secs:05.2f}"

def write_srt_from_segments(segments: Iterable[TimeRange], dest: Path) -> Path:
    lines: List[str] = []
    for idx, (start, end, text) in enumerate(segments, start=1):
        start_ts = format_timestamp(start)
        end_ts = format_timestamp(end)
        lines.append(str(idx))
        lines.append(f"{start_ts.replace('.', ',')} --> {end_ts.replace('.', ',')}")

        # Security: Sanitize text to prevent SRT injection via double newlines
        # Replace 2+ newlines (with optional whitespace) with a single newline
        safe_text = re.sub(r'\n\s*\n', '\n', text.strip())

        lines.append(safe_text)
        lines.append("")  # blank line separator
    dest.write_text("\n".join(lines), encoding="utf-8")
    return dest


import textwrap
import math

class config:
    MAX_SUB_LINE_CHARS = 40

def _wrap_lines(
    words,
    max_chars=config.MAX_SUB_LINE_CHARS,
    max_lines=2,
):
    if not words:
        return []

    # Balanced Wrapping Logic
    # Calculate ideal width to distribute text evenly across max_lines
    
    # Heuristic: roughly 15 chars min width seems reasonable to avoid single-word lines if possible
    MIN_WIDTH = 15  
    
    # Effective cap: 
    # If 1 line: we allow wider text (up to 55-60 chars) to try and fit it.
    # If >1 lines: we strictly follow MAX_SUB_LINE_CHARS (40) to ensure safety.
    max_width_cap = int(config.MAX_SUB_LINE_CHARS * 1.5) if max_lines == 1 else config.MAX_SUB_LINE_CHARS
    
    text = " ".join(words)
    total_len = len(text)
    
    # Target width per line
    target_width = math.ceil(total_len / max_lines)
    
    effective_width = max(MIN_WIDTH, target_width)
    effective_width = min(effective_width, max_width_cap)
    
    wrapped = textwrap.wrap(
        text,
        width=effective_width,
        break_long_words=True,
        break_on_hyphens=False,
        drop_whitespace=True,
    )
    
    print(f"DEBUG: max_lines={max_lines} | total_len={total_len} | target={target_width} | effective={effective_width} | result_lines={len(wrapped)}")
    for i, line in enumerate(wrapped):
        print(f"  Line {i+1}: {line} ({len(line)})")
        
    wrapped = wrapped[:max_lines]
    return [line.split() for line in wrapped]

print("\n--- TEST 1: Long Sentence (Should be 3 lines) ---")
long_text = "This is a very long sentence that I want to see split into three nice balanced lines if possible."
_wrap_lines(long_text.split(), max_lines=3)

print("\n--- TEST 2: Long Sentence (Should be 1 line if possible) ---")
med_text = "This is a medium sentence that might fit on one big line."
_wrap_lines(med_text.split(), max_lines=1)

print("\n--- TEST 3: Short Sentence (Should be 1 line) ---")
short_text = "Hello world."
_wrap_lines(short_text.split(), max_lines=3)

print("\n--- TEST 4: Massive Text (Checking cap) ---")
huge_text = "This is a massively long text that definitely exceeds all limits and should be truncated or wrapped fiercely."
_wrap_lines(huge_text.split(), max_lines=2)

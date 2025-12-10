
from dataclasses import dataclass
from typing import List, Optional

@dataclass
class Word:
    start: float
    end: float
    text: str
    probability: float = 1.0

@dataclass
class Cue:
    start: float
    end: float
    text: str
    words: Optional[List[Word]] = None

def _split_long_cues(cues: List[Cue], max_chars: int = 40) -> List[Cue]:
    new_cues = []
    
    for cue in cues:
        # If short enough, keep it
        if len(cue.text) <= max_chars:
            new_cues.append(cue)
            continue
            
        print(f"\nDEBUG: Splitting '{cue.text}' (len={len(cue.text)})")
        
        # Strategy: Use word timings if available
        if cue.words:
            current_words = []
            current_len = 0
            
            # Group words into chunks <= max_chars
            for w in cue.words:
                w_len = len(w.text) + 1 # +space
                
                # If adding this word exceeds limit, push current chunk as new cue
                if current_words and (current_len + w_len > max_chars):
                    # Create cue from current_words
                    chunk_text = " ".join([cw.text for cw in current_words])
                    chunk_start = current_words[0].start
                    chunk_end = current_words[-1].end
                    
                    # Gap filling: Ensure continuity? 
                    # Usually next cue starts at next word start. 
                    # Gap between chunks is naturally handled by their word timings.
                    
                    new_cues.append(Cue(
                        start=chunk_start,
                        end=chunk_end,
                        text=chunk_text,
                        words=list(current_words)
                    ))
                    print(f"  -> Created chunk: '{chunk_text}' ({chunk_start:.2f}-{chunk_end:.2f})")
                    
                    # Reset
                    current_words = [w]
                    current_len = w_len
                else:
                    current_words.append(w)
                    current_len += w_len
            
            # Flush final chunk
            if current_words:
                chunk_text = " ".join([cw.text for cw in current_words])
                chunk_start = current_words[0].start
                chunk_end = current_words[-1].end
                
                # Ensure the last chunk extends to the original cue end?
                # Sometimes word timings end before cue end (silence). 
                # Let's trust word timings for now, or stretch the last word?
                # Safer: use original cue end for the very last chunk if it's later.
                chunk_end = max(chunk_end, cue.end)
                
                new_cues.append(Cue(
                    start=chunk_start,
                    end=chunk_end,
                    text=chunk_text,
                    words=list(current_words)
                ))
                print(f"  -> Created chunk: '{chunk_text}' ({chunk_start:.2f}-{chunk_end:.2f})")

        else:
            # Fallback: No word timings (Interpolation)
            # Naive split by chars
            pass # TODO implement fallback if needed, but Whisper usually gives words
            new_cues.append(cue) # Just keep logical fallback for now

    return new_cues

# Test Data
words = [
    Word(0.0, 0.5, "This"), Word(0.5, 1.0, "is"), Word(1.0, 1.5, "a"),
    Word(1.5, 2.0, "very"), Word(2.0, 3.0, "long"), Word(3.0, 4.0, "subtitle"),
    Word(4.0, 4.5, "event"), Word(4.5, 5.0, "that"), Word(5.0, 6.0, "needs"),
    Word(6.0, 7.0, "splitting.")
]
full_text = "This is a very long subtitle event that needs splitting."
original_cue = Cue(0.0, 7.0, full_text, words)

print("--- Test split at 20 chars ---")
result = _split_long_cues([original_cue], max_chars=20)

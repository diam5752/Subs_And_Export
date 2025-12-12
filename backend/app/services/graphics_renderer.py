
from pathlib import Path
from typing import List, Tuple, Optional
import textwrap
from PIL import Image, ImageDraw, ImageFont
import numpy as np
from moviepy import VideoFileClip, ImageClip, CompositeVideoClip, TextClip, vfx
from backend.app.core import config
from backend.app.services.subtitles import Cue, WordTiming

# Constants for positioning
SAFE_MARGIN_X = config.DEFAULT_SUB_MARGIN_L
SAFE_MARGIN_Y_BOTTOM = config.DEFAULT_SUB_MARGIN_V # Approx 320 from bottom

def _get_font_path(font_name: str) -> str:
    """Resolve font path - crude fallback for system fonts."""
    # This is a simplification. Ideally use matplotlib font manager or hardcoded paths.
    # For macOS/Arial Black:
    possible_paths = [
        "/Library/Fonts/Arial Black.ttf",
        "/System/Library/Fonts/Supplemental/Arial Black.ttf",
        "/System/Library/Fonts/Helvetica.ttc",
        "/System/Library/Fonts/Supplemental/Arial.ttf"
    ]
    for p in possible_paths:
        if Path(p).exists():
            return p
    return "Arial" # PIL default fallback often fails, but let's hope.




def render_active_word_video(
    input_path: Path, 
    output_path: Path, 
    cues: List[Cue], 
    font: str = "Arial",
    font_size: int = config.DEFAULT_SUB_FONT_SIZE,
    primary_color: str = "#FFFF00", # Yellow
    secondary_color: str = "#FFFFFF", # White
    stroke_color: str = "black",
    stroke_width: int = 2,
    target_width: int = config.DEFAULT_WIDTH,
    target_height: int = config.DEFAULT_HEIGHT,
    max_lines: int = 2
) -> Path:
    """
    Renders video with 'Active Word' (pop) style using MoviePy & PIL.
    """
    video = VideoFileClip(str(input_path))
    
    # 1. Resize & Pad (Normalize)
    w, h = video.size
    target_ratio = target_width / target_height
    ratio = w / h
    
    if ratio > target_ratio:
        new_w = target_width
        new_h = int(target_width / ratio)
    else:
        new_h = target_height
        new_w = int(target_height * ratio)
        
    video = video.with_effects([vfx.Resize(new_size=(new_w, new_h))])
    
    # Pad to target size (centered)
    pad_left = (target_width - new_w) // 2
    pad_top = (target_height - new_h) // 2
    video = video.with_effects([vfx.Margin(left=pad_left, top=pad_top, right=target_width-new_w-pad_left, bottom=target_height-new_h-pad_top, color=(0,0,0))])
    
    W, H = video.size # Should be target_width, target_height
    
    # Create temporary PIL image for text measuring
    font_path = _get_font_path(font)
    
    clips = [video] # Start with base video
    
    for cue in cues:
        if not cue.words:
             continue 
        
        
        # SPECIAL CASE: Single Word Mode (True Karaoke)
        # If max_lines is 0, we only want to show the ACTIVE word, centered.
        if max_lines == 0:
             cursor_time = cue.start
             
             def make_single_word_clip(start, end, word_obj: Optional[WordTiming]):
                if end <= start: return None
                if not word_obj: return None 

                # Make PIL Image
                img = Image.new('RGBA', (W, H), (0, 0, 0, 0))
                draw = ImageDraw.Draw(img)
                
                try:
                    sw_font = ImageFont.truetype(font_path, font_size)
                except:
                    sw_font = ImageFont.load_default()

                # Measure
                w_len = draw.textlength(word_obj.text, font=sw_font)
                
                # Center
                x = (W - w_len) // 2
                y = H - SAFE_MARGIN_Y_BOTTOM - font_size 
                
                draw.text((x, y), word_obj.text, font=sw_font, fill=primary_color, stroke_width=stroke_width, stroke_fill=stroke_color, anchor="lt")
                
                img_np = np.array(img)
                return ImageClip(img_np).with_start(start).with_duration(end - start).with_position(("center", "top"))

             for idx, word_timing in enumerate(cue.words):
                w_end = word_timing.end
                if idx == len(cue.words) - 1: w_end = max(w_end, cue.end) 
                
                clip = make_single_word_clip(word_timing.start, w_end, word_timing)
                if clip: clips.append(clip)
             
             continue 

        # 1. LAYOUT: Wrap words into lines based on target width
        current_font_size = font_size
        lines_struct: List[List[WordTiming]] = []
        pil_font = None 
        space_width = 0
        
        # Safe margin for text rendering (horizontal padding)
        max_text_width = target_width - (SAFE_MARGIN_X * 2)

        # Optimization for Single Line (max_lines=1): Calculate exact fit
        if max_lines == 1:
             try:
                base_font = ImageFont.truetype(font_path, font_size)
             except:
                base_font = ImageFont.load_default()
             
             measure_draw = ImageDraw.Draw(Image.new('RGB', (1, 1)))
             full_text_width = 0
             space_w = measure_draw.textlength(" ", font=base_font)
             
             for idx, w in enumerate(cue.words):
                 full_text_width += measure_draw.textlength(w.text, font=base_font)
                 if idx < len(cue.words) - 1:
                     full_text_width += space_w
             
             if full_text_width > max_text_width:
                 scale = max_text_width / full_text_width
                 current_font_size = int(font_size * scale * 0.95) # 5% safety margin
                 current_font_size = max(current_font_size, 10) # Hard floor 10px
        
        # Dynamic Scaler Loop: Try to fit in max_lines, reduce font size if needed
        
        min_font_size = int(font_size * 0.4) # Allow shrinking down to 40%
        if max_lines == 1: min_font_size = 10 # Allow very small for single line constraint

        
        while current_font_size >= min_font_size:
            try:
                pil_font = ImageFont.truetype(font_path, current_font_size)
            except Exception:
                pil_font = ImageFont.load_default()
            
            measure_img = Image.new('RGB', (1, 1))
            measure_draw = ImageDraw.Draw(measure_img)
            space_width = measure_draw.textlength(" ", font=pil_font)
            
            # Try to layout
            lines_struct = []
            current_line: List[WordTiming] = []
            current_line_width = 0
            
            # Safe margin for text rendering (horizontal padding)
            max_text_width = target_width - (SAFE_MARGIN_X * 2)

            for word in cue.words:
                word_w = measure_draw.textlength(word.text, font=pil_font)
                
                # If line is not empty, add space width
                added_width = word_w
                if current_line:
                    added_width += space_width
                    
                if current_line and (current_line_width + added_width > max_text_width):
                    # Wrap to new line
                    lines_struct.append(current_line)
                    current_line = [word]
                    current_line_width = word_w
                else:
                    current_line.append(word)
                    current_line_width += added_width
            
            if current_line:
                lines_struct.append(current_line)
                
            # Check if valid
            if len(lines_struct) <= max_lines:
                break # Fits!
            
            # Failed, reduce font size
            current_font_size = int(current_font_size * 0.9)
            if current_font_size < min_font_size:
                print(f"Warning: Could not fit text in {max_lines} lines even at smallest font. Keeping overflow.")
                break # Keep the overflow version if we can't shrink further

        # 2. Render Clips
        cursor_time = cue.start
        
        # Helper to generate image for a specific state
        def make_clip(start, end, active_word_ref: Optional[WordTiming]):
            if end <= start: return None
            
            # Make PIL Image
            img = Image.new('RGBA', (W, H), (0, 0, 0, 0))
            draw = ImageDraw.Draw(img)
            
            # Calculate text block height
            # Approx height: lines * (font_size + spacing)
            line_spacing = 10
            # Get accurate line height using bbox?
            ascent, descent = pil_font.getmetrics()
            line_height = ascent + descent + line_spacing
            text_block_height = len(lines_struct) * line_height
            
            # Position text at bottom margin
            start_y = H - SAFE_MARGIN_Y_BOTTOM - text_block_height
            
            # Draw
            current_y = start_y
            
            for line_words in lines_struct:
                # Measure line for centering
                line_w_total = 0
                widths = []
                for i, w in enumerate(line_words):
                    w_len = draw.textlength(w.text, font=pil_font)
                    widths.append(w_len)
                    line_w_total += w_len
                    if i < len(line_words) - 1:
                        line_w_total += space_width
                
                current_x = (W - line_w_total) // 2
                
                for i, w in enumerate(line_words):
                    is_active = (w is active_word_ref)
                    fill_color = primary_color if is_active else secondary_color
                    
                    draw.text(
                        (current_x, current_y), 
                        w.text, 
                        font=pil_font, 
                        fill=fill_color, 
                        stroke_width=stroke_width, 
                        stroke_fill=stroke_color,
                        anchor="lt"
                    )
                    
                    current_x += widths[i]
                    if i < len(line_words) - 1:
                        current_x += space_width
                
                current_y += line_height

            # Convert to numpy for MoviePy
            img_np = np.array(img)
            clip = ImageClip(img_np).with_start(start).with_duration(end - start).with_position(("center", "top"))
            return clip

        # Iterate words to fill timeline
        for idx, word_timing in enumerate(cue.words):
            # Spacer before word (Silence/Gap)
            if word_timing.start > cursor_time:
                # dim state (no active word)
                gap_clip = make_clip(cursor_time, word_timing.start, None)
                if gap_clip: clips.append(gap_clip)
            
            # Active Word
            # For the last word, extend to the end of the cue to prevent early cutoff
            w_end = word_timing.end
            if idx == len(cue.words) - 1:
                w_end = max(w_end, cue.end)

            word_clip = make_clip(word_timing.start, w_end, word_timing)
            if word_clip: clips.append(word_clip)
            
            cursor_time = w_end
            
        # Spacer after last word
        if cursor_time < cue.end:
            tail_clip = make_clip(cursor_time, cue.end, None)
            if tail_clip: clips.append(tail_clip)
            
    # 3. Write
    final = CompositeVideoClip(clips)
    final.write_videofile(
        str(output_path), 
        fps=video.fps or 30, 
        codec="libx264", 
        audio_codec="aac",
        logger=None # Silent
    )
    
    return output_path



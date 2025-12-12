
import pytest
from unittest.mock import MagicMock, patch
import numpy as np
from PIL import Image

from backend.app.services.renderers.active_word import ActiveWordRenderer
from backend.app.services.renderers.karaoke import KaraokeRenderer
from backend.app.services.subtitles import Cue, WordTiming

# --- Fixtures ---

@pytest.fixture
def mock_font_utils():
    with patch("backend.app.services.renderers.active_word.load_font") as mock_load_aw, \
         patch("backend.app.services.renderers.active_word.get_font_path") as mock_path_aw, \
         patch("backend.app.services.renderers.karaoke.load_font") as mock_load_k, \
         patch("backend.app.services.renderers.karaoke.get_font_path") as mock_path_k:
        
        mock_font = MagicMock()
        mock_font.getmetrics.return_value = (10, 5) # ascent, descent
        
        # Determine text length based on string length for predictable testing
        def fake_length(text, font=None):
            return len(text) * 10

        mock_draw = MagicMock()
        mock_draw.textlength.side_effect = fake_length
        
        # We can't easily mock ImageDraw.Draw inside the class without patching ImageDraw
        # But we can assume load_font returns our mock_font
        mock_load_aw.return_value = mock_font
        mock_load_k.return_value = mock_font
        
        yield {
            "load_aw": mock_load_aw,
            "load_k": mock_load_k
        }

@pytest.fixture
def sample_cues():
    return [
        Cue(
            start=0.0, 
            end=2.0, 
            text="Hello World", 
            words=[
                WordTiming(0.0, 1.0, "Hello"),
                WordTiming(1.0, 2.0, "World")
            ]
        )
    ]

# --- ActiveWordRenderer Tests ---

def test_active_word_renderer_initialization(sample_cues):
    renderer = ActiveWordRenderer(
        cues=sample_cues,
        font="Arial",
        font_size=40,
        primary_color="yellow",
        stroke_color="black",
        stroke_width=2,
        width=100,
        height=100,
        margin_bottom=20
    )
    assert renderer.width == 100
    assert len(renderer.cue_starts) == 1

def test_active_word_rendering_active_frame(sample_cues):
    # We need to patch ImageDraw to control text measurement inside render_frame
    with patch("PIL.ImageDraw.Draw") as mock_draw_cls:
        mock_draw = MagicMock()
        mock_draw_cls.return_value = mock_draw
        mock_draw.textlength.return_value = 50.0
        
        renderer = ActiveWordRenderer(
            cues=sample_cues,
            font="Arial",
            font_size=40,
            primary_color="yellow",
            stroke_color="black",
            stroke_width=2,
            width=200,
            height=200,
            margin_bottom=20
        )
        
        # t=0.5 -> "Hello" is active
        frame = renderer.render_frame(0.5)
        
        assert isinstance(frame, np.ndarray)
        assert frame.shape == (200, 200, 4) # RGBA
        
        # Verify text was drawn
        assert mock_draw.text.call_count == 1
        args, kwargs = mock_draw.text.call_args
        assert args[1] == "Hello"
        assert kwargs["fill"] == "yellow"

def test_active_word_rendering_empty_frame(sample_cues):
    renderer = ActiveWordRenderer(
        cues=sample_cues,
        font="Arial",
        font_size=40,
        primary_color="yellow",
        stroke_color="black",
        stroke_width=2,
        width=200,
        height=200,
        margin_bottom=20
    )
    
    # t=5.0 -> No active cue
    frame = renderer.render_frame(5.0)
    
    # Should be fully transparent
    assert np.all(frame == 0)

# --- KaraokeRenderer Tests ---

def test_karaoke_renderer_rendering(sample_cues):
    with patch("PIL.ImageDraw.Draw") as mock_draw_cls:
        mock_draw = MagicMock()
        mock_draw_cls.return_value = mock_draw
        mock_draw.textlength.return_value = 20.0 # Small words fit on one line
        
        renderer = KaraokeRenderer(
            cues=sample_cues,
            max_lines=2,
            font="Arial",
            font_size=40,
            primary_color="yellow",
            secondary_color="white",
            stroke_color="black",
            stroke_width=2,
            width=200,
            height=200,
            margin_bottom=20,
            margin_x=10
        )
        
        # t=0.5 -> "Hello" active, "World" inactive
        frame = renderer.render_frame(0.5)
        
        assert isinstance(frame, np.ndarray)
        # Should draw both words
        assert mock_draw.text.call_count == 2
        
        # Check colors
        calls = mock_draw.text.call_args_list
        # First word "Hello" should be primary color
        assert calls[0].kwargs['fill'] == "yellow"
        assert calls[0].args[1] == "Hello"
        
        # Second word "World" should be secondary color
        assert calls[1].kwargs['fill'] == "white"
        assert calls[1].args[1] == "World"

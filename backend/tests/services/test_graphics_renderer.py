import pytest
from unittest.mock import MagicMock, patch, ANY
from pathlib import Path
from backend.app.services.graphics_renderer import render_active_word_video

@pytest.fixture
def mock_moviepy():
    with patch("backend.app.services.graphics_renderer.VideoFileClip") as mock_vfc, \
         patch("backend.app.services.graphics_renderer.CompositeVideoClip") as mock_cvc, \
         patch("backend.app.services.graphics_renderer.VideoClip") as mock_vc, \
         patch("backend.app.services.graphics_renderer.resize_and_pad_video") as mock_resize:
         
        mock_video = MagicMock()
        mock_video.size = (1080, 1920)
        mock_video.duration = 10.0
        mock_video.fps = 30
        mock_vfc.return_value = mock_video
        mock_resize.return_value = mock_video
        
        mock_final = MagicMock()
        mock_cvc.return_value = mock_final
        
        yield {
            "vfc": mock_vfc,
            "cvc": mock_cvc,
            "vc": mock_vc,
            "resize": mock_resize,
            "video": mock_video,
            "final": mock_final
        }

@pytest.fixture
def mock_renderers():
    with patch("backend.app.services.graphics_renderer.ActiveWordRenderer") as mock_active, \
         patch("backend.app.services.graphics_renderer.KaraokeRenderer") as mock_karaoke:
         yield {"active": mock_active, "karaoke": mock_karaoke}

def test_render_active_word_video_legacy_mode(tmp_path, mock_moviepy, mock_renderers):
    # max_lines = 0 -> ActiveWordRenderer
    output = tmp_path / "out.mp4"
    render_active_word_video(
        input_path=Path("in.mp4"),
        output_path=output,
        cues=[],
        max_lines=0
    )
    
    # Verify ActiveWordRenderer initialized
    mock_renderers["active"].assert_called_once()
    mock_renderers["karaoke"].assert_not_called()
    
    # Verify VideoClip created with make_frame
    mock_moviepy["vc"].assert_called_once()
    
    # Verify Composite
    mock_moviepy["cvc"].assert_called_once()
    
    # Verify Write
    mock_moviepy["final"].write_videofile.assert_called_with(
        str(output), fps=30, codec="libx264", audio_codec="aac", logger=None
    )

    # Verify make_frame function works (invoke it)
    # The make_frame is passed to VideoClip constructor.
    # VideoClip(make_frame, duration=...)
    args, _ = mock_moviepy["vc"].call_args
    make_frame_func = args[0]
    
    # Setup renderer mock to return something
    mock_renderer_instance = mock_renderers["active"].return_value
    mock_renderer_instance.render_frame.return_value = "FRAME"
    
    assert make_frame_func(1.0) == "FRAME"
    mock_renderer_instance.render_frame.assert_called_with(1.0)

def test_render_active_word_video_karaoke_mode(tmp_path, mock_moviepy, mock_renderers):
    # max_lines = 2 -> KaraokeRenderer
    output = tmp_path / "out.mp4"
    render_active_word_video(
        input_path=Path("in.mp4"),
        output_path=output,
        cues=[],
        max_lines=2
    )
    
    mock_renderers["karaoke"].assert_called_once()
    mock_renderers["active"].assert_not_called()

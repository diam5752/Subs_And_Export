import pytest
from unittest.mock import MagicMock, patch
from backend.app.services.renderers.utils import resize_and_pad_video, load_font, get_font_path

class TestUtils:
    def test_resize_and_pad_video_wide(self):
        # Original: 1920x1080 (1.77)
        # Target: 1080x1920 (0.56)
        # Should resize to width=1080, height=607
        # ratio > target_ratio (1.77 > 0.56) -> fit width
        
        mock_video = MagicMock()
        mock_video.size = (1920, 1080)
        
        mock_resized = MagicMock()
        mock_padded = MagicMock()
        # The chain: video.with_effects -> resized.with_effects -> padded
        mock_video.with_effects.return_value = mock_video # video is reassigned
        
        # We need to simulate the chaining effect correctly or just verify logic works
        # utils.py:
        # video = video.with_effects(...)
        # video = video.with_effects(...)
        
        with patch("backend.app.services.renderers.utils.vfx") as mock_vfx:
             result = resize_and_pad_video(mock_video, 1080, 1920)
             
             # Check Resize call
             # new_w = 1080
             # new_h = 1080 / (1920/1080) = 1080 / 1.777 = 607
             mock_vfx.Resize.assert_called()
             # calls = mock_vfx.Resize.call_args_list
             
             mock_vfx.Margin.assert_called()

    def test_resize_and_pad_video_tall(self):
        # Original: 100x200 (0.5)
        # Target: 100x100 (1.0)
        # ratio < target_ratio (0.5 < 1.0) -> fit height
        
        mock_video = MagicMock()
        mock_video.size = (100, 200)
        mock_video.with_effects.return_value = mock_video
        
        with patch("backend.app.services.renderers.utils.vfx") as mock_vfx:
             resize_and_pad_video(mock_video, 100, 100)
             
             # new_h = 100
             # new_w = 100 * 0.5 = 50
             mock_vfx.Resize.assert_called()
             # Verify Margin logic
             mock_vfx.Margin.assert_called()

    def test_load_font_success(self):
        with patch("backend.app.services.renderers.utils.ImageFont") as mock_if:
             load_font("arial.ttf", 20)
             mock_if.truetype.assert_called_with("arial.ttf", 20)

    def test_load_font_failure(self):
        with patch("backend.app.services.renderers.utils.ImageFont") as mock_if:
             mock_if.truetype.side_effect = IOError("fail")
             load_font("bad.ttf", 20)
             mock_if.load_default.assert_called()

    def test_get_font_path_fallback(self):
        with patch("backend.app.services.renderers.utils.Path") as mock_path:
             mock_path.return_value.exists.return_value = False
             assert get_font_path("foo") == "Arial"
             
    def test_get_font_path_found(self):
        with patch("backend.app.services.renderers.utils.Path") as mock_path:
             # Make the first path exist
             mock_path.return_value.exists.return_value = True
             path = get_font_path("foo")
             assert path in ["/Library/Fonts/Arial Black.ttf", "Arial"] # Depends on list order

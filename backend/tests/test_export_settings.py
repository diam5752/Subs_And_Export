"""
SUBTITLE EXPORT SETTINGS REGRESSION TESTS

These tests verify that subtitle settings (color, max_lines, highlight_style)
are correctly passed through the export pipeline and applied in the generated ASS file.
"""
import json
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from backend.app.services import subtitles, video_processing, ffmpeg_utils
from backend.app.services.subtitle_types import Cue, WordTiming
from backend.app.core import config


class TestSubtitleSettingsExport:
    """Test subtitle settings are correctly applied during export."""

    @pytest.fixture
    def mock_export_setup(self, monkeypatch, tmp_path):
        """Common setup for export tests."""
        artifact_dir = tmp_path / "artifacts"
        artifact_dir.mkdir()
        input_video = tmp_path / "in.mp4"
        input_video.touch()
        (artifact_dir / "in.srt").touch()
        
        # Create transcription.json with word timings
        transcription_data = [
            {
                "start": 0,
                "end": 2,
                "text": "Hello World",
                "words": [
                    {"start": 0, "end": 1, "text": "Hello"},
                    {"start": 1, "end": 2, "text": "World"}
                ]
            }
        ]
        (artifact_dir / "transcription.json").write_text(
            json.dumps(transcription_data), encoding="utf-8"
        )
        
        job_store = MagicMock()
        job = MagicMock()
        job.user_id = "u1"
        job.result_data = {"subtitle_size": 100}
        job_store.get_job.return_value = job
        
        def fake_burn(*args, **kwargs):
            Path(args[2]).touch()
        monkeypatch.setattr(ffmpeg_utils, "run_ffmpeg_with_subs", fake_burn)
        
        return {
            "artifact_dir": artifact_dir,
            "input_video": input_video,
            "job_store": job_store,
        }

    def test_export_applies_white_color(self, monkeypatch, mock_export_setup):
        """REGRESSION: Verify WHITE color is applied in exports (not default yellow)."""
        setup = mock_export_setup
        
        style_calls = []
        ass_output = setup["artifact_dir"] / "in.ass"
        
        def capture_style(*args, **kwargs):
            style_calls.append(kwargs)
            ass_output.touch()
            return ass_output
        
        monkeypatch.setattr(subtitles, "create_styled_subtitle_file", capture_style)
        
        video_processing.generate_video_variant(
            "job1", setup["input_video"], setup["artifact_dir"], "1280x720",
            setup["job_store"], "u1",
            subtitle_settings={
                "subtitle_color": "&H00FFFFFF",  # WHITE
                "karaoke_enabled": True,
                "subtitle_size": 100,
            }
        )
        
        assert len(style_calls) == 1
        assert style_calls[0]["primary_color"] == "&H00FFFFFF", \
            f"Expected WHITE color, got {style_calls[0]['primary_color']}"

    def test_export_applies_cyan_color(self, monkeypatch, mock_export_setup):
        """REGRESSION: Verify CYAN color is applied in exports."""
        setup = mock_export_setup
        
        style_calls = []
        ass_output = setup["artifact_dir"] / "in.ass"
        
        def capture_style(*args, **kwargs):
            style_calls.append(kwargs)
            ass_output.touch()
            return ass_output
        
        monkeypatch.setattr(subtitles, "create_styled_subtitle_file", capture_style)
        
        video_processing.generate_video_variant(
            "job1", setup["input_video"], setup["artifact_dir"], "1280x720",
            setup["job_store"], "u1",
            subtitle_settings={
                "subtitle_color": "&H00FFFF00",  # CYAN
                "karaoke_enabled": True,
                "subtitle_size": 100,
            }
        )
        
        assert len(style_calls) == 1
        assert style_calls[0]["primary_color"] == "&H00FFFF00"

    def test_export_applies_max_lines_zero(self, monkeypatch, mock_export_setup):
        """REGRESSION: Verify max_lines=0 (single word mode) is applied in exports."""
        setup = mock_export_setup
        
        style_calls = []
        ass_output = setup["artifact_dir"] / "in.ass"
        
        def capture_style(*args, **kwargs):
            style_calls.append(kwargs)
            ass_output.touch()
            return ass_output
        
        monkeypatch.setattr(subtitles, "create_styled_subtitle_file", capture_style)
        
        video_processing.generate_video_variant(
            "job1", setup["input_video"], setup["artifact_dir"], "1280x720",
            setup["job_store"], "u1",
            subtitle_settings={
                "max_subtitle_lines": 0,  # Single word mode
                "highlight_style": "active-graphics",
                "karaoke_enabled": True,
                "subtitle_size": 100,
            }
        )
        
        assert len(style_calls) == 1
        assert style_calls[0]["max_lines"] == 0
        assert style_calls[0]["highlight_style"] == "active"  # Should be converted

    def test_export_applies_double_line_mode(self, monkeypatch, mock_export_setup):
        """REGRESSION: Verify max_lines=2 (double line mode) is applied in exports."""
        setup = mock_export_setup
        
        style_calls = []
        ass_output = setup["artifact_dir"] / "in.ass"
        
        def capture_style(*args, **kwargs):
            style_calls.append(kwargs)
            ass_output.touch()
            return ass_output
        
        monkeypatch.setattr(subtitles, "create_styled_subtitle_file", capture_style)
        
        video_processing.generate_video_variant(
            "job1", setup["input_video"], setup["artifact_dir"], "1280x720",
            setup["job_store"], "u1",
            subtitle_settings={
                "max_subtitle_lines": 2,
                "karaoke_enabled": True,
                "subtitle_size": 100,
            }
        )
        
        assert len(style_calls) == 1
        assert style_calls[0]["max_lines"] == 2

    def test_export_all_settings_combined(self, monkeypatch, mock_export_setup):
        """
        REGRESSION: Verify ALL settings are correctly applied together:
        - Color: MAGENTA
        - Max lines: 1 (single line)
        - Highlight style: active
        """
        setup = mock_export_setup
        
        style_calls = []
        ass_output = setup["artifact_dir"] / "in.ass"
        
        def capture_style(*args, **kwargs):
            style_calls.append(kwargs)
            ass_output.touch()
            return ass_output
        
        monkeypatch.setattr(subtitles, "create_styled_subtitle_file", capture_style)
        
        video_processing.generate_video_variant(
            "job1", setup["input_video"], setup["artifact_dir"], "1280x720",
            setup["job_store"], "u1",
            subtitle_settings={
                "subtitle_color": "&H00FF00FF",  # MAGENTA
                "max_subtitle_lines": 1,
                "highlight_style": "active-graphics",
                "karaoke_enabled": True,
                "subtitle_size": 100,
                "shadow_strength": 6,
            }
        )
        
        assert len(style_calls) == 1
        assert style_calls[0]["primary_color"] == "&H00FF00FF"
        assert style_calls[0]["max_lines"] == 1
        assert style_calls[0]["highlight_style"] == "active"
        assert style_calls[0]["shadow_strength"] == 6

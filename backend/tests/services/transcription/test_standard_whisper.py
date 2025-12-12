import pytest
from unittest.mock import MagicMock, patch, mock_open, ANY
from pathlib import Path
import sys

# Mock pywhispercpp before importing the module under test to avoid ImportError in test environment
# if the package is not actually installed.
mock_pywhispercpp = MagicMock()
sys.modules["pywhispercpp"] = mock_pywhispercpp
sys.modules["pywhispercpp.model"] = mock_pywhispercpp

from backend.app.services.transcription.standard_whisper import (
    StandardTranscriber,
    _normalize_text,
    _format_timestamp,
    _write_srt_from_segments
)
from backend.app.services.subtitles import Cue

class TestStandardWhisperHelpers:
    def test_normalize_text(self):
        assert _normalize_text("Héllo Wörld") == "HELLO WORLD"
        assert _normalize_text("UPPERCASE") == "UPPERCASE"
        assert _normalize_text("") == ""
        assert _normalize_text("άλογο") == "ΑΛΟΓΟ" # Greek check

    def test_format_timestamp(self):
        # 0s
        assert _format_timestamp(0.0) == "0:00:00.00"
        # 1h 1m 1.5s = 3661.5
        assert _format_timestamp(3661.5) == "1:01:01.50"
        # Check comma replacement happens in SRT writer, not here. 
        # Here it returns dot.
        assert "." in _format_timestamp(1.5)

    def test_write_srt_from_segments(self, tmp_path):
        segments = [
            (0.0, 1.5, "First line"),
            (1.5, 3.0, "Second line"),
        ]
        dest = tmp_path / "test.srt"
        _write_srt_from_segments(segments, dest)
        
        content = dest.read_text(encoding="utf-8")
        expected_timestamp_1 = "0:00:00,00 --> 0:00:01,50"
        expected_timestamp_2 = "0:00:01,50 --> 0:00:03,00"
        
        assert "1" in content
        assert expected_timestamp_1 in content
        assert "First line" in content
        assert "2" in content
        assert expected_timestamp_2 in content
        assert "Second line" in content


class TestStandardTranscriber:
    @pytest.fixture
    def mock_segment(self):
        # Mock result segment from pywhispercpp
        # t0, t1 are in centiseconds
        seg1 = MagicMock()
        seg1.t0 = 0
        seg1.t1 = 150 # 1.5s
        seg1.text = " Hello World "
        
        seg2 = MagicMock()
        seg2.t0 = 150
        seg2.t1 = 300 # 3.0s
        seg2.text = " Test Segment "
        
        return [seg1, seg2]

    def test_transcribe_success(self, tmp_path, mock_segment):
        # Setup mocks
        mock_model_instance = MagicMock()
        mock_model_instance.transcribe.return_value = mock_segment
        
        # We need to mock the import INSIDE the method or ensure it uses our sys.modules mock
        with patch("backend.app.services.transcription.standard_whisper.config") as mock_config:
            mock_config.WHISPERCPP_MODEL = "base"
            mock_config.WHISPERCPP_LANGUAGE = "en"
            
            # Since we masked sys.modules at top, the import inside transcribe should return our mock
            # We assume pywhispercpp.model.Model is our mock
            mock_pywhispercpp.Model.return_value = mock_model_instance
            
            transcriber = StandardTranscriber()
            audio_path = tmp_path / "audio.mp3"
            audio_path.touch()
            
            callback = MagicMock()
            
            srt_path, cues = transcriber.transcribe(
                audio_path,
                output_dir=tmp_path,
                progress_callback=callback
            )
            
            # Verification
            assert srt_path == tmp_path / "audio.srt"
            assert srt_path.exists()
            assert len(cues) == 2
            
            # Verify Cues
            assert cues[0].text == "HELLO WORLD"
            assert cues[0].start == 0.0
            assert cues[0].end == 1.5
            
            assert cues[1].text == "TEST SEGMENT"
            assert cues[1].start == 1.5
            assert cues[1].end == 3.0
            
            # Verify Callback
            assert callback.call_count >= 3 # 5.0, 15.0, 85.0, 100.0?
            callback.assert_any_call(100.0)
            
            # Verify Model usage
            mock_pywhispercpp.Model.assert_called_with("base", print_realtime=False, print_progress=False)
            mock_model_instance.transcribe.assert_called()

    def test_transcribe_import_error(self, tmp_path):
        # To test ImportError, we need to make the import fail.
        # We can simulate this by setting sys.modules ENTRY to None or side_effect on import?
        # Standard generic approach is patch.dict(sys.modules, {'pywhispercpp.model': None}) ? 
        # But we already set it to MagicMock at top level.
        
        # We can patch 'builtins.__import__' but that's risky.
        # Better: use patch.dict on sys.modules to remove it, AND ensure finding it raises ImportError.
        
        with patch.dict(sys.modules):
            # Remove our mock
            del sys.modules["pywhispercpp"]
            del sys.modules["pywhispercpp.model"]
            
            # Also need to make sure import machinery doesn't find it.
            # But wait, if it's not installed in env, it will raise ImportError natively.
            # If it IS installed, we need to hide it.
            
            # A robust way is to patch the module name in the import statement? No.
            
            # We can use a side_effect on the Model constructor if the import succeeds but checking it fails? 
            # No, the Except block catches ImportError on IMPORT.
            pass

            # Force import failure by patching sys.modules with a Key that raises error on access? No.
            # Standard way:
            with patch.dict(sys.modules, {'pywhispercpp': None, 'pywhispercpp.model': None}):
                 # When a module is None in sys.modules, import raises ModuleNotFoundError (subclass of ImportError)
                 transcriber = StandardTranscriber()
                 
                 with pytest.raises(RuntimeError) as excinfo:
                     transcriber.transcribe(Path("dummy.mp3"), tmp_path)
                 
                 assert "pywhispercpp not installed" in str(excinfo.value)

    def test_transcribe_params(self, tmp_path, mock_segment):
        mock_model_instance = MagicMock()
        mock_model_instance.transcribe.return_value = mock_segment
        mock_pywhispercpp.Model.return_value = mock_model_instance
        
        transcriber = StandardTranscriber()
        audio_path = tmp_path / "audio.mp3"
        audio_path.touch()
        
        transcriber.transcribe(
            audio_path,
            output_dir=tmp_path,
            language="fr",
            model="tiny"
        )
        
        mock_pywhispercpp.Model.assert_called_with("tiny", print_realtime=False, print_progress=False)
        mock_model_instance.transcribe.assert_called_with(str(audio_path), language="fr", n_threads=ANY)

    def test_transcribe_empty_segments(self, tmp_path):
        # Handling segments with empty text
        mock_model_instance = MagicMock()
        seg_empty = MagicMock()
        seg_empty.text = "   "
        seg_empty.t0 = 0
        seg_empty.t1 = 100
        
        mock_model_instance.transcribe.return_value = [seg_empty]
        mock_pywhispercpp.Model.return_value = mock_model_instance
        
        transcriber = StandardTranscriber()
        audio_path = tmp_path / "audio.mp3"
        audio_path.touch()
        
        _, cues = transcriber.transcribe(audio_path, output_dir=tmp_path)
        
        assert len(cues) == 0

    def test_transcribe_normalized_empty_skip(self, tmp_path):
        mock_model_instance = MagicMock()
        seg_bad = MagicMock()
        # Combining acute accent only - normalizes to empty string
        seg_bad.text = "\u0301" 
        seg_bad.t0 = 0
        seg_bad.t1 = 100
        
        mock_model_instance.transcribe.return_value = [seg_bad]
        mock_pywhispercpp.Model.return_value = mock_model_instance
        
        transcriber = StandardTranscriber()
        audio_path = tmp_path / "audio.mp3"
        audio_path.touch()
        
        _, cues = transcriber.transcribe(audio_path, output_dir=tmp_path)
        
        assert len(cues) == 0

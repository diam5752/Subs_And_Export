from unittest.mock import patch

from backend.app.services.transcription.groq_cloud import GroqTranscriber
from backend.app.services.transcription.openai_cloud import OpenAITranscriber


def test_groq_transcriber_delegates(tmp_path):
    with patch("backend.app.services.transcription.groq_cloud.generate_subtitles_from_audio") as mock_gen:
        mock_gen.return_value = (tmp_path/"out.srt", [])

        t = GroqTranscriber()
        t.transcribe(tmp_path/"in.wav", tmp_path, language="fr")

        mock_gen.assert_called_with(
            tmp_path/"in.wav",
            output_dir=tmp_path,
            model_size="whisper-large-v3", # Default
            language="fr",
            provider="groq"
        )

def test_openai_transcriber_delegates(tmp_path):
    with patch("backend.app.services.transcription.openai_cloud.generate_subtitles_from_audio") as mock_gen:
        mock_gen.return_value = (tmp_path/"out.srt", [])

        t = OpenAITranscriber(api_key="k")
        t.transcribe(tmp_path/"in.wav", tmp_path, language="de")

        mock_gen.assert_called_with(
            tmp_path/"in.wav",
            output_dir=tmp_path,
            model_size="whisper-1",
            language="de",
            provider="openai",
            openai_api_key="k"
        )

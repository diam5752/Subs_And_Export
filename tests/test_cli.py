from pathlib import Path

from typer.testing import CliRunner

from greek_sub_publisher import subtitles
from greek_sub_publisher.cli import app


def test_process_command_invokes_pipeline(monkeypatch, tmp_path: Path) -> None:
    runner = CliRunner()
    input_file = tmp_path / "input.mp4"
    input_file.write_bytes(b"dummy video content")

    output_file = tmp_path / "output.mp4"
    sample_social = subtitles.SocialCopy(
        subtitles.PlatformCopy(title="TT", description="TikTok copy"),
        subtitles.PlatformCopy(title="YT", description="Shorts copy"),
        subtitles.PlatformCopy(title="IG", description="Instagram copy"),
    )

    def fake_process(input_video, output_video, **kwargs):
        output_video.write_bytes(b"done")
        if kwargs.get("generate_social_copy"):
            return output_video, sample_social
        return output_video

    monkeypatch.setattr("greek_sub_publisher.cli.normalize_and_stub_subtitles", fake_process)
    result = runner.invoke(app, [str(input_file), "--output", str(output_file)])

    assert result.exit_code == 0
    assert output_file.exists()
    assert "Processed video saved to" in result.stdout
    assert "TikTok title: TT" in result.stdout

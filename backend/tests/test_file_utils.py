from pathlib import Path

import pytest

from backend.app.api.endpoints import file_utils


def test_link_or_copy_file_uses_hard_link_when_available(tmp_path: Path) -> None:
    source = tmp_path / "source.bin"
    destination = tmp_path / "nested" / "destination.bin"
    source.write_bytes(b"subtitle-video")

    file_utils.link_or_copy_file(source, destination)

    assert destination.read_bytes() == b"subtitle-video"
    assert source.stat().st_ino == destination.stat().st_ino


def test_link_or_copy_file_falls_back_to_copy(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    source = tmp_path / "source.bin"
    destination = tmp_path / "destination.bin"
    source.write_bytes(b"subtitle-video")

    def fail_hard_link(_source: Path, _destination: Path) -> None:
        raise OSError("cross-device link")

    monkeypatch.setattr(file_utils.os, "link", fail_hard_link)
    file_utils.link_or_copy_file(source, destination)

    assert destination.read_bytes() == source.read_bytes()
    assert source.stat().st_ino != destination.stat().st_ino


def test_link_or_copy_file_refuses_to_overwrite(tmp_path: Path) -> None:
    source = tmp_path / "source.bin"
    destination = tmp_path / "destination.bin"
    source.write_bytes(b"source")
    destination.write_bytes(b"existing")

    with pytest.raises(FileExistsError):
        file_utils.link_or_copy_file(source, destination)

    assert destination.read_bytes() == b"existing"


def test_sanitize_download_filename_preserves_unicode_and_real_extension() -> None:
    # REGRESSION: the static route exposed processed_*.mp4 instead of the requested export name.
    assert file_utils.sanitize_download_filename(
        "Ε Isous_subs.mp4",
        "processed_1080x1920.mp4",
    ) == "Ε Isous_subs.mp4"
    assert file_utils.sanitize_download_filename(
        "../../bad\r\nname.exe",
        "processed.srt",
    ) == "bad__name.srt"
    assert file_utils.sanitize_download_filename(None, "processed.vtt") == "processed.vtt"

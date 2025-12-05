"""Backend video processing delegates to the shared pipeline implementation."""
from greek_sub_publisher.video_processing import (  # noqa: F401
    _build_filtergraph,
    _input_audio_is_aac,
    _persist_artifacts,
    _run_ffmpeg_with_subs,
    normalize_and_stub_subtitles,
)

__all__ = [
    "_build_filtergraph",
    "_input_audio_is_aac",
    "_persist_artifacts",
    "_run_ffmpeg_with_subs",
    "normalize_and_stub_subtitles",
]

from __future__ import annotations

import sys
import tempfile
from pathlib import Path

import streamlit as st


# Ensure src/ is on the import path when running via `streamlit run app.py`
ROOT = Path(__file__).resolve().parent
SRC = ROOT / "src"
if SRC.exists() and str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from greek_sub_publisher import config  # type: ignore  # noqa: E402
from greek_sub_publisher.subtitles import SocialCopy  # type: ignore  # noqa: E402
from greek_sub_publisher.video_processing import (  # type: ignore  # noqa: E402
    normalize_and_stub_subtitles,
)


st.set_page_config(
    page_title="Greek Sub Publisher",
    page_icon="🇬🇷",
    layout="centered",
)

st.title("🇬🇷 Greek Sub Publisher")
st.write(
    "Normalize vertical videos, generate Greek subtitles, and draft social copy "
    "for TikTok, YouTube Shorts, and Instagram Reels."
)


def _render_social_copy(social: SocialCopy) -> None:
    st.subheader("Suggested platform copy")
    tabs = st.tabs(["TikTok", "YouTube Shorts", "Instagram Reels"])

    with tabs[0]:
        st.markdown("**Title**")
        st.code(social.tiktok.title, language="text")
        st.markdown("**Description**")
        st.code(social.tiktok.description, language="text")

    with tabs[1]:
        st.markdown("**Title**")
        st.code(social.youtube_shorts.title, language="text")
        st.markdown("**Description**")
        st.code(social.youtube_shorts.description, language="text")

    with tabs[2]:
        st.markdown("**Title**")
        st.code(social.instagram.title, language="text")
        st.markdown("**Description**")
        st.code(social.instagram.description, language="text")


uploaded = st.file_uploader(
    "Upload a vertical video",
    type=["mp4", "mov", "mkv"],
    help="Files are processed on this machine. On Streamlit Cloud, they are processed on the app's server.",
)

use_llm = st.checkbox(
    "Use LLM for richer social copy (requires OPENAI_API_KEY)",
    value=False,
)

with st.expander("Advanced settings"):
    model_options = ["tiny", "base", "small", "medium", "large-v3"]
    default_model_index = (
        model_options.index(config.WHISPER_MODEL_SIZE)
        if config.WHISPER_MODEL_SIZE in model_options
        else model_options.index("medium")
    )
    model_size = st.radio(
        "Whisper model size",
        options=model_options,
        index=default_model_index,
        help="Smaller models are faster but less accurate.",
        horizontal=True,
    )
    language = st.text_input(
        "Language code (leave blank for default)",
        value=config.WHISPER_LANGUAGE or "",
    ) or None
    beam_size = st.number_input(
        "Beam size (0 = default)",
        min_value=0,
        max_value=10,
        value=0,
        help="Higher beam size can improve quality at the cost of speed.",
    )
    best_of = st.number_input(
        "Best-of candidates",
        min_value=1,
        max_value=10,
        value=1,
    )
    video_crf = st.slider(
        "Video quality (CRF)",
        min_value=10,
        max_value=30,
        value=config.DEFAULT_VIDEO_CRF,
        help="Lower values mean higher quality and larger files.",
    )
    audio_copy = st.checkbox(
        "Copy original audio instead of re-encoding",
        value=False,
    )
    llm_model = None
    llm_temperature = 0.6
    if use_llm:
        llm_model = st.text_input(
            "LLM model name",
            value=config.SOCIAL_LLM_MODEL,
        )
        llm_temperature = st.slider(
            "LLM temperature",
            min_value=0.0,
            max_value=2.0,
            value=0.6,
            step=0.05,
        )

if uploaded is not None:
    st.info(f"Uploaded file: `{uploaded.name}`")

    if st.button("Generate subtitles and social copy"):
        with st.spinner("Processing video... this may take a while."):
            try:
                with tempfile.TemporaryDirectory() as tmp_dir:
                    tmp = Path(tmp_dir)
                    input_path = tmp / uploaded.name
                    input_path.write_bytes(uploaded.getbuffer())

                    output_path = tmp / f"{input_path.stem}{config.DEFAULT_OUTPUT_SUFFIX}.mp4"
                    artifact_dir = tmp / "artifacts"

                    result = normalize_and_stub_subtitles(
                        input_path,
                        output_path,
                        model_size=model_size,
                        language=language,
                        beam_size=beam_size or None,
                        best_of=best_of,
                        video_crf=video_crf,
                        audio_copy=audio_copy,
                        generate_social_copy=True,
                        use_llm_social_copy=use_llm,
                        llm_model=llm_model,
                        llm_temperature=llm_temperature,
                        artifact_dir=artifact_dir,
                    )

                    processed_path: Path
                    social: SocialCopy

                    if isinstance(result, tuple):
                        processed_path, social = result
                    else:
                        processed_path = result
                        # Social copy should always be present when generate_social_copy=True,
                        # but guard just in case.
                        social = None  # type: ignore[assignment]

                    st.success("Processing finished.")

                    st.subheader("Preview")
                    st.video(str(processed_path))

                    st.download_button(
                        "Download processed video",
                        data=processed_path.read_bytes(),
                        file_name=processed_path.name,
                        mime="video/mp4",
                    )

                    transcript_file = artifact_dir / "transcript.txt"
                    if transcript_file.exists():
                        st.download_button(
                            "Download transcript.txt",
                            data=transcript_file.read_bytes(),
                            file_name="transcript.txt",
                            mime="text/plain",
                        )

                    social_json = artifact_dir / "social_copy.json"
                    if social_json.exists():
                        st.download_button(
                            "Download social_copy.json",
                            data=social_json.read_bytes(),
                            file_name="social_copy.json",
                            mime="application/json",
                        )

                    if "social" in locals() and social is not None:
                        _render_social_copy(social)
            except Exception as exc:  # pragma: no cover - UI-only path
                st.error(f"Processing failed: {exc}")

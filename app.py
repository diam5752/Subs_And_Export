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
from greek_sub_publisher.ui import (  # type: ignore  # noqa: E402
    load_css, 
    render_sidebar_header,
    render_dashboard_header,
    render_stat_card,
    render_social_copy,
)

st.set_page_config(
    page_title="Greek Sub Publisher",
    page_icon="🇬🇷",
    layout="wide",
    initial_sidebar_state="expanded",
)

# Load Technical SaaS CSS
load_css(SRC / "greek_sub_publisher" / "styles.css")

# --- SIDEBAR: CONFIGURATION & INPUTS ---
with st.sidebar:
    render_sidebar_header()
    
    # 1. Primary Action: Upload
    uploaded = st.file_uploader(
        "Upload Video",
        type=["mp4", "mov", "mkv"],
        help="Upload a vertical video for processing.",
        label_visibility="collapsed",
        key="video_uploader"
    )
    
    if uploaded:
        st.success(f"Ready: {uploaded.name}")
    
    st.markdown("###") # Spacer

    # 2. Primary Action: Process
    process_btn = st.button("Start Processing", type="primary", use_container_width=True, disabled=not uploaded)


    st.markdown("###") # Spacer
    st.markdown("---")

    # 3. Gamified Configuration
    st.markdown("### ⚙️ Configuration")
    
    # Transcription Quality
    st.markdown("**Transcription Speed vs. Accuracy**")
    transcribe_mode = st.select_slider(
        "Select Transcription Mode",
        options=["Fast", "Balanced", "Best"],
        value="Balanced",
        label_visibility="collapsed",
        help="Fast: Uses 'tiny' model (quick, less accurate). Balanced: Uses 'medium' model (good tradeoff). Best: Uses 'large-v3' model (slowest, highest accuracy)."
    )
    
    # Map selection to model size
    model_map = {"Fast": "tiny", "Balanced": "medium", "Best": "large-v3"}
    model_size = model_map[transcribe_mode]

    # Video Quality
    st.markdown("**Video Output Quality**")
    video_quality = st.select_slider(
        "Select Video Quality",
        options=["Low Size", "Balanced", "High Quality"],
        value="Balanced",
        label_visibility="collapsed",
        help="Low Size: Lower bitrate (CRF 28). Balanced: Good for social media (CRF 23). High Quality: Near lossless (CRF 18)."
    )
    
    # Map selection to CRF
    crf_map = {"Low Size": 28, "Balanced": 23, "High Quality": 18}
    video_crf = crf_map[video_quality]

    # AI Enrichment
    st.markdown("**AI Intelligence**")
    use_llm = st.toggle(
        "Enable AI Enrichment", 
        value=False,
        help="If enabled, an AI model will analyze the transcript to generate viral titles and descriptions for TikTok, Shorts, and Reels."
    )
    
    llm_model = None
    llm_temperature = 0.6
    
    if use_llm:
        st.caption("AI Model Active: Generating Social Copy")
        llm_model = config.SOCIAL_LLM_MODEL # Default to config, hidden for simplicity

    # Hidden/Advanced defaults
    language = None # Auto-detect
    beam_size = 0
    best_of = 1
    audio_copy = False


# --- MAIN DASHBOARD ---
render_dashboard_header()

# Processing Logic
if process_btn and uploaded:
    with st.spinner("Processing media pipeline..."):
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
                    social = None  # type: ignore[assignment]

                # Store results in session state
                st.session_state["processed_path"] = str(processed_path)
                st.session_state["social"] = social
                st.session_state["artifact_dir"] = str(artifact_dir)
                
                st.session_state["processing_done"] = True
                st.session_state["processed_video_bytes"] = processed_path.read_bytes()
                st.session_state["processed_video_name"] = processed_path.name
                
                transcript_file = artifact_dir / "transcript.txt"
                if transcript_file.exists():
                    st.session_state["transcript_bytes"] = transcript_file.read_bytes()
                
                social_json = artifact_dir / "social_copy.json"
                if social_json.exists():
                    st.session_state["social_json_bytes"] = social_json.read_bytes()
                
                st.toast("Processing Pipeline Completed Successfully", icon="✅")

        except Exception as exc:
            st.error(f"Pipeline Error: {exc}")

# Results View
if "processing_done" in st.session_state and st.session_state["processing_done"]:
    
    # Top Row: Video + Downloads
    col_vid, col_actions = st.columns([1.5, 1])
    
    with col_vid:
        st.video(st.session_state["processed_video_bytes"])
    
    with col_actions:
        st.markdown("### Downloads")
        
        st.download_button(
            "Download Video (MP4)",
            data=st.session_state["processed_video_bytes"],
            file_name=st.session_state["processed_video_name"],
            mime="video/mp4",
            key="btn_download_video",
            use_container_width=True
        )
        
        if "transcript_bytes" in st.session_state:
            st.download_button(
                "Download Transcript (TXT)",
                data=st.session_state["transcript_bytes"],
                file_name="transcript.txt",
                mime="text/plain",
                key="btn_download_transcript",
                use_container_width=True
            )

        if "social_json_bytes" in st.session_state:
            st.download_button(
                "Download Metadata (JSON)",
                data=st.session_state["social_json_bytes"],
                file_name="social_copy.json",
                mime="application/json",
                key="btn_download_json",
                use_container_width=True
            )

    # Bottom Row: Social Copy
    if "social" in st.session_state and st.session_state["social"]:
        st.markdown("---")
        render_social_copy(st.session_state["social"])

else:
    # Empty State
    st.markdown(
        """
        <div style="
            display: flex; 
            flex-direction: column;
            align-items: center; 
            justify-content: center; 
            height: 400px; 
            background-color: #18181b; 
            border: 1px dashed #27272a; 
            border-radius: 8px; 
            color: #52525b;
            margin-top: 20px;">
            <div style="font-size: 48px; margin-bottom: 16px; opacity: 0.5;">📼</div>
            <div style="font-weight: 500; color: #a1a1aa;">No Media Loaded</div>
            <div style="font-size: 13px; margin-top: 8px;">Upload a video in the sidebar to begin processing.</div>
        </div>
        """,
        unsafe_allow_html=True
    )

from __future__ import annotations

import os
import sys
import tempfile
import tomllib
import platform
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


def _load_ai_settings() -> dict[str, object]:
    """Load AI defaults from .streamlit/config.toml if present."""
    settings: dict[str, object] = {
        "enable_by_default": False,
        "model": config.SOCIAL_LLM_MODEL,
        "temperature": 0.6,
    }
    cfg_path = ROOT / ".streamlit" / "app_settings.toml"
    if not cfg_path.exists():
        return settings

    try:
        with cfg_path.open("rb") as fh:
            cfg = tomllib.load(fh)
        ai_cfg = cfg.get("ai", {}) if isinstance(cfg, dict) else {}
        if isinstance(ai_cfg, dict):
            if "enable_by_default" in ai_cfg:
                settings["enable_by_default"] = bool(ai_cfg["enable_by_default"])
            if "model" in ai_cfg and ai_cfg["model"]:
                settings["model"] = str(ai_cfg["model"])
            if "temperature" in ai_cfg:
                try:
                    settings["temperature"] = float(ai_cfg["temperature"])
                except (TypeError, ValueError):
                    pass
    except Exception:
        # If config parsing fails, keep safe defaults
        pass
    return settings


# --- SIDEBAR: CONFIGURATION & INPUTS ---
with st.sidebar:
    render_sidebar_header()
    
    ai_settings = _load_ai_settings()
    
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
        options=["Fast", "Balanced", "Turbo", "Best"],
        value="Turbo",  # Default to Turbo for best balance
        label_visibility="collapsed",
        help="Fast: Tiny model (Fastest). Balanced: Medium model. Turbo: Distilled Large-v3 (6x faster than Best, high accuracy). Best: Large-v3 (Slowest)."
    )
    
    if transcribe_mode == "Best":
        st.warning("⚠️ 'Best' mode uses a very large model. On a standard Mac, this may take 20+ minutes for long videos. Use 'Turbo' for similar quality at 6x speed.", icon="🐢")
    
    # Map selection to model size
    model_map = {
        "Fast": "tiny", 
        "Balanced": "medium", 
        "Turbo": config.WHISPER_MODEL_TURBO,
        "Best": "large-v3"
    }
    model_size = model_map[transcribe_mode]
    
    # Optimize beam_size for speed
    # Turbo/Distilled models are trained for greedy search (beam_size=1)
    beam_size_map = {"Fast": 1, "Balanced": 1, "Turbo": 1, "Best": 2}
    beam_size = beam_size_map[transcribe_mode]

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
    
    # Check if API key is available
    has_api_key = bool(
        os.getenv("OPENAI_API_KEY") or 
        (hasattr(st, "secrets") and "OPENAI_API_KEY" in st.secrets)
    )
    
    use_llm = st.toggle(
        "Enable AI Enrichment", 
        value=bool(ai_settings["enable_by_default"]) and has_api_key,
        disabled=not has_api_key,
        help=(
            "Uses OpenAI GPT-4o-mini to generate viral titles and descriptions. "
            "Fast and professional results. Requires OPENAI_API_KEY in environment or Streamlit secrets."
        )
    )
    
    llm_model = None
    llm_temperature = float(ai_settings["temperature"])
    
    if use_llm:
        llm_model = str(ai_settings["model"])
        st.caption(f"⚡ AI Model Active: {llm_model} (OpenAI)")
    elif not has_api_key:
        st.caption("⚠️ Set OPENAI_API_KEY to enable AI enrichment")

    # Hidden/Advanced defaults
    language = "el" # Force Greek to prevent English hallucination
    best_of = 1
    audio_copy = False
    
    # Hardware Acceleration
    is_mac = platform.system() == "Darwin"
    use_hw_accel = st.checkbox(
        "Use Hardware Acceleration",
        value=is_mac and config.USE_HW_ACCEL,
        help="Use VideoToolbox (Mac) for faster encoding. May slightly change file size.",
        disabled=not is_mac
    )


# --- MAIN DASHBOARD ---
render_dashboard_header()

# Processing Logic
if process_btn and uploaded:
    import time
    
    # Create placeholders for progress tracking
    progress_bar = st.progress(0.0)
    status_text = st.empty()
    time_text = st.empty()
    
    start_time = time.time()
    
    def update_progress(message: str, progress: float):
        """Update progress bar and time estimate."""
        # Update progress bar
        progress_bar.progress(progress / 100.0)
        
        # Update status message
        status_text.markdown(f"**{message}**")
        
        # Calculate time estimate
        elapsed = time.time() - start_time
        if progress > 5.0:  # Only show estimate after some progress
            estimated_total = (elapsed / progress) * 100
            remaining = estimated_total - elapsed
            
            if remaining > 60:
                time_str = f"~{int(remaining / 60)} min {int(remaining % 60)}s remaining"
            else:
                time_str = f"~{int(remaining)}s remaining"
            
            time_text.markdown(f"*{time_str}*")
    
    try:
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp = Path(tmp_dir)
            input_path = tmp / uploaded.name
            input_path.write_bytes(uploaded.getbuffer())

            output_path = tmp / f"{input_path.stem}{config.DEFAULT_OUTPUT_SUFFIX}.mp4"
            artifact_dir = tmp / "artifacts"

            # Get API key for LLM if enabled
            api_key = None
            if use_llm:
                api_key = os.getenv("OPENAI_API_KEY")
                if not api_key and hasattr(st, "secrets") and "OPENAI_API_KEY" in st.secrets:
                    api_key = st.secrets["OPENAI_API_KEY"]

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
                llm_api_key=api_key,
                artifact_dir=artifact_dir,
                use_hw_accel=use_hw_accel,
                progress_callback=update_progress,
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
            
            # Clear progress indicators and show success
            progress_bar.empty()
            status_text.empty()
            time_text.empty()
            st.toast("Processing Pipeline Completed Successfully", icon="✅")

    except Exception as exc:
        progress_bar.empty()
        status_text.empty()
        time_text.empty()
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

from __future__ import annotations

import os
import sys
import tempfile
import tomllib
import platform
import traceback
import secrets
from pathlib import Path
from typing import Any, Dict

import streamlit as st

# --- Helper utilities -----------------------------------------------------


def _configure_page() -> None:
    """Apply shared Streamlit page configuration and styles."""
    st.set_page_config(
        page_title="Greek Sub Publisher",
        page_icon="🇬🇷",
        layout="wide",
        initial_sidebar_state="expanded",
    )


def _has_secret_key(key: str) -> bool:
    """Safely detect a secret without requiring a configured secrets file."""
    try:
        return hasattr(st, "secrets") and key in st.secrets
    except Exception:
        # Streamlit raises when no secrets.toml is present; treat as missing.
        return False


def _resolve_openai_api_key() -> str | None:
    """Return an OpenAI API key from env vars or Streamlit secrets."""
    env_key = os.getenv("OPENAI_API_KEY")
    if env_key:
        return env_key

    try:
        if _has_secret_key("OPENAI_API_KEY"):
            return st.secrets.get("OPENAI_API_KEY")  # type: ignore[attr-defined]
    except Exception:
        return None
    return None


def _should_autorun() -> bool:
    """Detect whether the app is running inside a Streamlit runtime."""
    return st.runtime.exists()


# Ensure src/ is on the import path when running via `streamlit run app.py`
ROOT = Path(__file__).resolve().parent
SRC = ROOT / "src"
if SRC.exists() and str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from greek_sub_publisher import auth, config, history, metrics, tiktok, login_ui  # type: ignore  # noqa: E402
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

USER_STORE = auth.UserStore()
HISTORY_STORE = history.HistoryStore()


def _get_query_params() -> dict[str, str]:
    """Normalize query params for oauth callbacks."""
    # st.query_params is a dict-like object in newer Streamlit versions
    params = st.query_params
    normalized: dict[str, str] = {}
    for key, val in params.items():
        if isinstance(val, list):
            normalized[key] = val[0]
        else:
            normalized[key] = val
    return normalized


def _clear_query_params() -> None:
    """Remove query params to avoid re-processing callbacks."""
    st.query_params.clear()


def _log_ui_error(exc: Exception, context: dict | None = None) -> None:
    """Best-effort logging for UI-triggered pipeline errors."""
    event: dict[str, object] = {
        "status": "error",
        "error": f"{type(exc).__name__}: {exc}",
        "traceback": traceback.format_exc(),
    }
    if context:
        event.update(context)
    metrics.log_pipeline_metrics(event)


def _clear_processing_state() -> None:
    """Clear any stale results before a new run."""
    keys = [
        "processing_done",
        "processed_path",
        "processed_video_bytes",
        "processed_video_name",
        "transcript_bytes",
        "social_json_bytes",
        "artifact_dir",
        "social",
    ]
    for k in keys:
        st.session_state.pop(k, None)


def _set_current_user(user: auth.User) -> None:
    st.session_state["user"] = user.to_session()


def _current_user() -> auth.User | None:
    data = st.session_state.get("user")
    if not data:
        return None
    stored = USER_STORE.get_user_by_email(data.get("email", ""))
    if stored:
        return stored
    return auth.User(
        id=data.get("id", ""),
        email=data.get("email", ""),
        name=data.get("name", "User"),
        provider=data.get("provider", "local"),
    )


def _logout_user() -> None:
    for key in ("user", "tiktok_tokens", "google_oauth_state", "google_auth_url", "tiktok_oauth_state", "tiktok_auth_url"):
        st.session_state.pop(key, None)


def _handle_oauth_callbacks(params: dict[str, str]) -> None:
    """Handle Google and TikTok OAuth redirects."""
    code = params.get("code")
    state = params.get("state")
    handled = False

    if code and state and state == st.session_state.get("google_oauth_state"):
        cfg = auth.google_oauth_config()
        if cfg:
            try:
                profile = auth.exchange_google_code(cfg, code)
                user = USER_STORE.upsert_google_user(
                    profile["email"], profile["name"], profile.get("sub") or ""
                )
                _set_current_user(user)
                st.success(f"Signed in as {user.email}")
            except Exception as exc:
                st.error(f"Google sign-in failed: {exc}")
        handled = True
        # Clear state regardless of config success to avoid loops
        st.session_state.pop("google_oauth_state", None)
        st.session_state.pop("google_auth_url", None)

    # Local fallback: if state was lost (e.g., app restarted) but we are on localhost, still try to exchange
    elif code and state and not st.session_state.get("google_oauth_state"):
        cfg = auth.google_oauth_config()
        if cfg and cfg.get("redirect_uri", "").startswith("http://localhost"):
            try:
                profile = auth.exchange_google_code(cfg, code)
                user = USER_STORE.upsert_google_user(
                    profile["email"], profile["name"], profile.get("sub") or ""
                )
                _set_current_user(user)
                st.success(f"Signed in as {user.email}")
            except Exception as exc:
                st.error(f"Google sign-in failed: {exc}")
            handled = True

    if code and state and state == st.session_state.get("tiktok_oauth_state"):
        cfg = tiktok.config_from_env()
        if cfg:
            try:
                tokens = tiktok.exchange_code_for_token(cfg, code)
                st.session_state["tiktok_tokens"] = tokens
                st.success("TikTok connected")
            except Exception as exc:
                st.error(f"TikTok connection failed: {exc}")
        handled = True
        st.session_state.pop("tiktok_oauth_state", None)
        st.session_state.pop("tiktok_auth_url", None)

    if handled:
        _clear_query_params()


def _record_processing_history(
    user: auth.User,
    uploaded_name: str,
    output_path: Path,
    artifact_dir: Path,
    params: Dict[str, Any],
) -> None:
    try:
        HISTORY_STORE.record_event(
            user,
            "process",
            summary=f"Processed {uploaded_name}",
            data={
                "output_path": str(output_path),
                "artifact_dir": str(artifact_dir),
                **params,
            },
        )
    except Exception:
        # History is best-effort; never block UI.
        pass


def _record_tiktok_history(user: auth.User, payload: Dict[str, Any]) -> None:
    try:
        HISTORY_STORE.record_event(
            user,
            "tiktok_upload",
            summary="Uploaded video to TikTok",
            data={"response": payload},
        )
    except Exception:
        pass


def _get_tiktok_tokens() -> tiktok.TikTokTokens | None:
    tokens = st.session_state.get("tiktok_tokens")
    if isinstance(tokens, tiktok.TikTokTokens):
        return tokens
    if isinstance(tokens, dict):
        try:
            return tiktok.TikTokTokens(**tokens)
        except Exception:
            return None
    return None


def _load_ai_settings(settings_path: Path | None = None) -> dict[str, object]:
    """Load AI defaults from .streamlit/config.toml if present."""
    settings: dict[str, object] = {
        "enable_by_default": False,
        "model": config.SOCIAL_LLM_MODEL,
        "temperature": 0.6,
    }
    cfg_path = settings_path or (ROOT / ".streamlit" / "app_settings.toml")
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


def run_app() -> None:  # pragma: no cover
    _configure_page()
    load_css(SRC / "greek_sub_publisher" / "styles.css")

    # Process OAuth callbacks before rendering the UI
    _handle_oauth_callbacks(_get_query_params())
    
    # --- AUTHENTICATION CHECK ---
    user = _current_user()
    
    if not user:
        # Render the new centered login page
        authenticated_user = login_ui.render_login_page(USER_STORE)
        if authenticated_user:
            _set_current_user(authenticated_user)
            st.rerun()
        st.stop()  # Stop rendering the rest of the app until logged in
    
    
    # --- SIDEBAR: CONFIGURATION & INPUTS ---
    with st.sidebar:
        render_sidebar_header()
    
        st.markdown("### Account")
        if user:
            st.success(f"Signed in as {user.name} ({user.email})")
            if st.button("Log out", use_container_width=True, type="secondary"):
                _logout_user()
                st.rerun()
    
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
        process_btn = st.button(
            "Start Processing",
            type="primary",
            use_container_width=True,
            disabled=not uploaded,
        )
    
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
        
        # Decoder settings tuned for accuracy-first on M-series
        beam_size_map = {"Fast": 1, "Balanced": 1, "Turbo": 1, "Best": 3}
        beam_size = beam_size_map[transcribe_mode]
        
        best_of_map = {"Fast": 1, "Balanced": 1, "Turbo": 1, "Best": 3}
        best_of = best_of_map[transcribe_mode]
    
        condition_map = {"Fast": False, "Balanced": False, "Turbo": False, "Best": True}
        condition_on_previous_text = condition_map[transcribe_mode]
    
        temperature_map = {"Fast": 0.0, "Balanced": 0.0, "Turbo": 0.0, "Best": None}
        decode_temperature = temperature_map[transcribe_mode]
        
        # Use float16 for all modes - int8_float16 was slower on this hardware
        compute_type = config.WHISPER_COMPUTE_TYPE
        
        chunk_length = config.WHISPER_CHUNK_LENGTH
        batch_size = config.WHISPER_BATCH_SIZE
    
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

        resolved_api_key = _resolve_openai_api_key()
        has_api_key = resolved_api_key is not None

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

        context_prompt = st.text_area(
            "Context prompt (names/terms)",
            placeholder="Speaker names, brand terms, or domain context to boost accuracy",
            help="Optional hint to the model for better accuracy on names and jargon.",
        )

        # Hidden/Advanced defaults
        language = "el" # Force Greek to prevent English hallucination
        audio_copy = None

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
    
    if user:
        recent_events = HISTORY_STORE.recent_for_user(user, limit=6)
        if recent_events:
            st.markdown("### Recent activity")
            for evt in recent_events:
                st.markdown(f"- `{evt.ts}` — **{evt.summary}** ({evt.kind})")
            st.markdown("---")
    
    # Processing Logic
    if process_btn and uploaded:
        import time
        
        # Clear previous results to avoid stale state
        _clear_processing_state()
        
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
            # Use a persistent temp directory per run so the output file
            # remains accessible for reading, even if processing is slow.
            tmp_dir = tempfile.mkdtemp(prefix="gsp-run-")
            tmp = Path(tmp_dir)
            input_path = tmp / uploaded.name
            input_path.write_bytes(uploaded.getbuffer())

            output_path = tmp / f"{input_path.stem}{config.DEFAULT_OUTPUT_SUFFIX}.mp4"
            artifact_dir = tmp / "artifacts"

            # Get API key for LLM if enabled
            api_key = resolved_api_key if use_llm else None

            result = normalize_and_stub_subtitles(
                input_path,
                output_path,
                model_size=model_size,
                language=language,
                compute_type=compute_type,
                beam_size=beam_size,
                best_of=best_of,
                temperature=decode_temperature,
                chunk_length=chunk_length,
                condition_on_previous_text=condition_on_previous_text,
                initial_prompt=context_prompt.strip() if context_prompt else None,
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
            
            try:
                st.session_state["processed_video_bytes"] = processed_path.read_bytes()
                st.session_state["processed_video_name"] = processed_path.name
                st.session_state["processing_done"] = True
            except FileNotFoundError as exc:
                _log_ui_error(exc, {"processed_path": str(processed_path)})
                st.error(f"Pipeline Error: Processed video missing at {processed_path}")
                st.session_state["processing_done"] = False
                raise
    
            transcript_file = artifact_dir / "transcript.txt"
            if transcript_file.exists():
                st.session_state["transcript_bytes"] = transcript_file.read_bytes()
            
            social_json = artifact_dir / "social_copy.json"
            if social_json.exists():
                st.session_state["social_json_bytes"] = social_json.read_bytes()
    
            if user:
                _record_processing_history(
                    user,
                    uploaded.name,
                    processed_path,
                    artifact_dir,
                    {
                        "model_size": model_size,
                        "video_crf": video_crf,
                        "use_llm": use_llm,
                    },
                )
            
            # Clear progress indicators and show success
            progress_bar.empty()
            status_text.empty()
            time_text.empty()
            st.toast("Processing Pipeline Completed Successfully", icon="✅")
    
        except Exception as exc:
            progress_bar.empty()
            status_text.empty()
            time_text.empty()
            _log_ui_error(
                exc,
                {
                    "model_size": model_size,
                    "device": config.WHISPER_DEVICE,
                    "compute_type": config.WHISPER_COMPUTE_TYPE,
                    "use_hw_accel": use_hw_accel,
                    "beam_size": beam_size,
                    "best_of": best_of,
                    "chunk_length": chunk_length,
                    "condition_on_previous_text": condition_on_previous_text,
                    "video_crf": video_crf,
                    "audio_copy": audio_copy,
                },
            )
            st.session_state["processing_done"] = False
            st.error(f"Pipeline Error: {exc}")
    
    # Results View
    if st.session_state.get("processing_done"):
        
        # Top Row: Video + Downloads
        col_vid, col_actions = st.columns([1.5, 1])
        
        with col_vid:
            if "processed_video_bytes" in st.session_state:
                st.video(st.session_state["processed_video_bytes"])
            else:
                st.info("Processed video is not available. Please re-run processing.")
        
        with col_actions:
            st.markdown("### Downloads")
            if "processed_video_bytes" in st.session_state and "processed_video_name" in st.session_state:
                st.download_button(
                    "Download Video (MP4)",
                    data=st.session_state["processed_video_bytes"],
                    file_name=st.session_state["processed_video_name"],
                    mime="video/mp4",
                    key="btn_download_video",
                    use_container_width=True,
                    type="primary"
                )
            else:
                st.caption("Video download unavailable due to a processing error.")
            
            if "transcript_bytes" in st.session_state:
                st.download_button(
                    "Download Transcript (TXT)",
                    data=st.session_state["transcript_bytes"],
                    file_name="transcript.txt",
                    mime="text/plain",
                    key="btn_download_transcript",
                    use_container_width=True,
                    type="secondary"
                )
    
            if "social_json_bytes" in st.session_state:
                st.download_button(
                    "Download Metadata (JSON)",
                    data=st.session_state["social_json_bytes"],
                    file_name="social_copy.json",
                    mime="application/json",
                    key="btn_download_json",
                    use_container_width=True,
                    type="secondary"
                )
    
        # Bottom Row: Social Copy
        if "social" in st.session_state and st.session_state["social"]:
            st.markdown("---")
            render_social_copy(st.session_state["social"])
    
        st.markdown("---")
        st.markdown("### Publish to TikTok")
        tiktok_cfg = tiktok.config_from_env()
        tiktok_tokens = _get_tiktok_tokens()
    
        if tiktok_cfg:
            if tiktok_tokens and tiktok_tokens.is_expired() and tiktok_tokens.refresh_token:
                try:
                    tiktok_tokens = tiktok.refresh_access_token(tiktok_cfg, tiktok_tokens.refresh_token)
                    st.session_state["tiktok_tokens"] = tiktok_tokens
                except Exception:
                    tiktok_tokens = None
                    st.warning("TikTok session expired. Please reconnect.")
    
            if not tiktok_tokens:
                if st.button("Connect TikTok", use_container_width=True, key="btn_tiktok_connect", type="primary"):
                    state = f"tiktok-{secrets.token_hex(8)}"
                    st.session_state["tiktok_oauth_state"] = state
                    st.session_state["tiktok_auth_url"] = tiktok.build_auth_url(tiktok_cfg, state=state)
                if st.session_state.get("tiktok_auth_url"):
                    try:
                        st.link_button(
                            "Authorize TikTok in new tab",
                            st.session_state["tiktok_auth_url"],
                            use_container_width=True,
                            type="primary",
                            key="btn_tiktok_link",
                        )
                    except Exception:
                        st.markdown(f"[Authorize TikTok]({st.session_state['tiktok_auth_url']})")
                st.caption("Stay signed in to this app during TikTok consent. You'll return here automatically.")
            else:
                processed_path = st.session_state.get("processed_path")
                if not processed_path:
                    st.info("No processed video available for upload.")
                else:
                    default_title = st.session_state["social"].tiktok.title if st.session_state.get("social") else st.session_state.get("processed_video_name", "TikTok Upload")
                    default_desc = st.session_state["social"].tiktok.description if st.session_state.get("social") else ""
                    tt_title = st.text_input("TikTok title", value=default_title, key="tiktok_title")
                    tt_desc = st.text_area("TikTok description", value=default_desc, height=140, key="tiktok_desc")
                    if st.button("Upload to TikTok", type="primary", use_container_width=True, key="btn_tiktok_upload"):
                        try:
                            payload = tiktok.upload_video(
                                tiktok_tokens,
                                Path(processed_path),
                                tt_title,
                                tt_desc,
                            )
                            st.success("TikTok upload request sent.")
                            _record_tiktok_history(user, payload)
                        except Exception as exc:
                            st.error(f"TikTok upload failed: {exc}")
    
        else:
            st.info("Set TIKTOK_CLIENT_KEY, TIKTOK_CLIENT_SECRET, and TIKTOK_REDIRECT_URI to enable TikTok uploads.")
    
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
                background-color: #121214; 
                border: 1px dashed #27272a; 
                border-radius: 12px; 
                color: #52525b;
                margin-top: 20px;">
                <div style="font-size: 48px; margin-bottom: 16px; opacity: 0.5;">📼</div>
                <div style="font-weight: 500; color: #a1a1aa;">No Media Loaded</div>
                <div style="font-size: 13px; margin-top: 8px;">Upload a video in the sidebar to begin processing.</div>
            </div>
            """,
            unsafe_allow_html=True
        )

if _should_autorun():  # pragma: no cover
    run_app()

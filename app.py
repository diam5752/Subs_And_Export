from __future__ import annotations

import os
import sys
import tempfile
import tomllib
import datetime
import platform
import traceback
import secrets
from pathlib import Path
from typing import Any, Dict

import streamlit as st
import extra_streamlit_components as stx

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

from greek_sub_publisher import auth, config, database, history, login_ui, metrics, tiktok  # type: ignore  # noqa: E402
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
    render_upload_hero,
)

DB = database.Database()
USER_STORE = auth.UserStore(db=DB)
SESSION_STORE = auth.SessionStore(db=DB)
HISTORY_STORE = history.HistoryStore(db=DB)


def _get_query_params() -> dict[str, str]:
    """Normalize query params for oauth callbacks (new + legacy APIs)."""
    raw: dict[str, object] = {}
    try:
        if hasattr(st, "query_params"):
            candidate = getattr(st, "query_params")
            if hasattr(candidate, "items"):
                raw = dict(candidate.items())  # type: ignore[arg-type]
        if not raw and hasattr(st, "experimental_get_query_params"):
            raw = st.experimental_get_query_params()  # type: ignore[attr-defined]
    except Exception:
        raw = {}

    normalized: dict[str, str] = {}
    for key, val in raw.items():
        if isinstance(val, list) and val:
            normalized[key] = str(val[0])
        elif val is not None:
            normalized[key] = str(val)
    return normalized


def _clear_query_params(preserve: set[str] | None = None) -> None:
    """Remove transient params to avoid re-processing callbacks."""
    preserve = preserve or {"auth_token"}
    try:
        for key in list(getattr(st, "query_params", {}).keys()):
            if key in preserve:
                continue
            getattr(st, "query_params").pop(key, None)
    except Exception:
        pass
    try:
        if hasattr(st, "experimental_get_query_params") and hasattr(
            st, "experimental_set_query_params"
        ):
            current = st.experimental_get_query_params()  # type: ignore[attr-defined]
            filtered = {k: v for k, v in current.items() if k in preserve}
            st.experimental_set_query_params(**filtered)  # type: ignore[attr-defined]
    except Exception:
        pass


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


def _get_cookie_manager():
    return stx.CookieManager(key="gsp_auth")


def _persist_session(user: auth.User, cookie_manager: stx.CookieManager) -> None:
    token = SESSION_STORE.issue_session(user)
    st.session_state["session_token"] = token
    st.session_state["user"] = user.to_session()
    
    # Store in cookie (30 days)
    expires = datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(seconds=auth.SessionStore.SESSION_TTL_SECONDS)
    cookie_manager.set("auth_token", token, expires_at=expires, key="set_auth_token")
    # Brief delay to allow cookie message to propagate to frontend
    import time
    time.sleep(0.5)


def _current_user(cookie_manager: stx.CookieManager) -> auth.User | None:
    token = st.session_state.get("session_token")
    
    # 1. Check Cookies if no session token
    if not token:
        token = cookie_manager.get("auth_token")

    if token:
        user = SESSION_STORE.authenticate(str(token))
        if user:
            st.session_state["session_token"] = str(token)
            st.session_state["user"] = user.to_session()
            return user
    
    # ... fallback to session_state
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


def _logout_user(cookie_manager: stx.CookieManager) -> None:
    token = st.session_state.pop("session_token", None)
    
    # Delete Cookie
    cookie_manager.delete("auth_token", key="delete_auth_token")

    if token:
        try:
            SESSION_STORE.revoke(str(token))
        except Exception:
            pass
    for key in (
        "user",
        "tiktok_tokens",
        "google_oauth_state",
        "google_auth_url",
        "tiktok_oauth_state",
        "tiktok_auth_url",
    ):
        st.session_state.pop(key, None)


def _handle_oauth_callbacks(params: dict[str, str], cookie_manager: stx.CookieManager, current_user: auth.User | None = None) -> None:
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
                _persist_session(user, cookie_manager)
                st.success(f"Signed in as {user.email}")
            except Exception as exc:
                st.error(f"Google sign-in failed: {exc}")
        handled = True
        # Clear state regardless of config success to avoid loops
        st.session_state.pop("google_oauth_state", None)
        st.session_state.pop("google_auth_url", None)

    # Local fallback: if state was lost (e.g., app restarted) but we are on localhost, still try to exchange
    # Only try this if we are not already logged in
    elif code and state and not st.session_state.get("google_oauth_state") and not current_user:
        cfg = auth.google_oauth_config()
        if cfg and cfg.get("redirect_uri", "").startswith("http://localhost"):
            try:
                profile = auth.exchange_google_code(cfg, code)
                user = USER_STORE.upsert_google_user(
                    profile["email"], profile["name"], profile.get("sub") or ""
                )
                _persist_session(user, cookie_manager)
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

    # --- AUTHENTICATION CHECK ---
    # Initialize CookieManager (this component needs to render once before we can read cookies)
    cookie_manager = _get_cookie_manager()
    
    # Check for existing session first (from session_state, not cookies on first render)
    user = None
    token = st.session_state.get("session_token")
    if token:
        user = SESSION_STORE.authenticate(str(token))
        if user:
            st.session_state["user"] = user.to_session()
    
    # Try to get from cookies (this may return None on first render before JS loads)
    if not user:
        try:
            cookie_token = cookie_manager.get("auth_token")
            if cookie_token:
                user = SESSION_STORE.authenticate(str(cookie_token))
                if user:
                    st.session_state["session_token"] = str(cookie_token)
                    st.session_state["user"] = user.to_session()
        except Exception:
            pass  # Cookie manager may not be ready yet
    
    # Fallback to session_state user data
    if not user:
        data = st.session_state.get("user")
        if data:
            stored = USER_STORE.get_user_by_email(data.get("email", ""))
            if stored:
                user = stored
            else:
                user = auth.User(
                    id=data.get("id", ""),
                    email=data.get("email", ""),
                    name=data.get("name", "User"),
                    provider=data.get("provider", "local"),
                )

    # Process OAuth callbacks
    _handle_oauth_callbacks(_get_query_params(), cookie_manager, current_user=user)
    
    # Refresh user if callbacks logged us in
    if not user:
        user = _current_user(cookie_manager)
    
    if not user:
        # Render the new centered login page
        authenticated_user = login_ui.render_login_page(USER_STORE)
        if authenticated_user:
            _persist_session(authenticated_user, cookie_manager)
            st.rerun()
        st.stop()  # Stop rendering the rest of the app until logged in
    
    
    # --- SIDEBAR: NAVIGATION ONLY ---
    with st.sidebar:
        render_sidebar_header()
    
        # User Profile Tiny Header
        if user:
            col_avatar, col_info = st.columns([1, 4])
            with col_avatar:
                st.markdown(
                    f'<div style="background:#2c2c2e;width:32px;height:32px;border-radius:50%;display:flex;align-items:center;justify-content:center;font-weight:700;">{user.name[0].upper()}</div>', 
                    unsafe_allow_html=True
                )
            with col_info:
                st.markdown(f"**{user.name}**")
                # st.caption(user.email) # Hide email to keep it clean

        st.markdown("###") # Spacer
            
        # --- Navigation ---
        view_mode = "Studio"
        if user:
            view_mode = st.radio(
                "Navigate", 
                ["Studio", "Library", "Profile"], 
                label_visibility="collapsed",
            )

        st.markdown("---")
        if st.button("Log out", use_container_width=True, type="secondary"):
            _logout_user(cookie_manager)
            st.rerun()
    
    # --- ROUTING ---
    if view_mode == "Library":
        from greek_sub_publisher import history_ui
        history_ui.render_library_page(user, HISTORY_STORE)
        return

    if view_mode == "Profile":
        login_ui.render_profile_page(user, USER_STORE)
        return

    # --- MAIN STUDIO VIEW ---
    render_dashboard_header()
    
    is_processed = st.session_state.get("processing_done", False)

    # 1. EMPTY STATE (Upload Hero)
    if "video_uploader" not in st.session_state or not st.session_state["video_uploader"]:
        render_upload_hero()

    uploaded = st.file_uploader(
        "Upload Video",
        type=["mp4", "mov", "mkv"],
        label_visibility="collapsed",
        key="video_uploader"
    )

    if uploaded:
        st.markdown("---") 
        
        # 2. STUDIO LAYOUT (2 Columns)
        col_preview, col_controls = st.columns([1.5, 1], gap="large")
        
        # --- LEFT: PREVIEW ---
        with col_preview:
            st.markdown("#### Preview")
            if is_processed and "processed_video_bytes" in st.session_state:
                st.video(st.session_state["processed_video_bytes"])
                st.caption(f"Output: {st.session_state.get('processed_video_name', 'video.mp4')}")
            else:
                st.video(uploaded)
                st.caption(f"Source: {uploaded.name}")

        # --- RIGHT: CONTROLS ---
        with col_controls:
            st.markdown("#### Configuration")
            
            # Smart Defaults & Configuration
            with st.expander("Processing Settings", expanded=not is_processed):
                ai_settings = _load_ai_settings()
                
                # Transcription Mode
                transcribe_mode = st.select_slider(
                    "Speed / Accuracy",
                    options=["Fast", "Balanced", "Turbo", "Best"],
                    value="Turbo",
                    help="Turbo provides the best balance of speed and accuracy (Large-v3 Distilled)."
                )

                # Quality / Size
                video_quality = st.select_slider(
                    "Output Quality",
                    options=["Low Size", "Balanced", "High Quality"],
                    value="Balanced"
                )

                # AI Features
                resolved_api_key = _resolve_openai_api_key()
                has_api_key = resolved_api_key is not None
                
                use_llm = st.toggle(
                    "AI Viral Intelligence",
                    value=bool(ai_settings["enable_by_default"]) and has_api_key,
                    disabled=not has_api_key,
                    help="Generate viral titles and descriptions using GPT-4o."
                )
                
                if use_llm:
                    context_prompt = st.text_area("Context Hints", placeholder="Names, specific terms...", height=80)
                else:
                    context_prompt = ""

                # Hardware Info
                if platform.system() == "Darwin" and config.USE_HW_ACCEL:
                    st.caption("🚀 Apple Silicon Acceleration Active")


            # ACTIONS
            st.markdown("###")
            
            # Map settings
            model_map = {"Fast": "tiny", "Balanced": "medium", "Turbo": config.WHISPER_MODEL_TURBO, "Best": "large-v3"}
            model_size = model_map[transcribe_mode]
            
            beam_size = 3 if transcribe_mode == "Best" else 1
            best_of = 3 if transcribe_mode == "Best" else 1
            condition_on_previous_text = True if transcribe_mode == "Best" else False
            decode_temperature = None if transcribe_mode == "Best" else 0.0
            
            crf_map = {"Low Size": 28, "Balanced": 23, "High Quality": 18}
            video_crf = crf_map[video_quality]

            # Primary Process Button
            process_btn = st.button(
                "✨ Start Magic Processing", 
                type="primary", 
                use_container_width=True,
                disabled=is_processed # Optional: disable if already done to prevent accidental re-run? No, user might want to re-run with new settings.
            )
            
            # Progress UI Containers
            progress_bar = st.empty()
            status_text = st.empty()


            # --- EXECUTION LOGIC ---
            if process_btn:
                import time
                _clear_processing_state()
                
                # Setup progress
                p_bar = progress_bar.progress(0.0)
                
                def update_progress(message: str, progress: float):
                    p_bar.progress(progress / 100.0)
                    status_text.markdown(f"**{message}**")

                try:
                    start_time = time.time()
                    
                    # Temp file handling
                    tmp_dir = tempfile.mkdtemp(prefix="gsp-run-")
                    tmp = Path(tmp_dir)
                    input_path = tmp / uploaded.name
                    input_path.write_bytes(uploaded.getbuffer())

                    output_path = tmp / f"{input_path.stem}{config.DEFAULT_OUTPUT_SUFFIX}.mp4"
                    artifact_dir = tmp / "artifacts"
                    
                    api_key = resolved_api_key if use_llm else None
                    llm_model = str(ai_settings["model"]) if use_llm else None
                    
                    # Call Pipeline
                    result = normalize_and_stub_subtitles(
                        input_path,
                        output_path,
                        model_size=model_size,
                        language="el", # Fixed Greek
                        compute_type=config.WHISPER_COMPUTE_TYPE,
                        beam_size=beam_size,
                        best_of=best_of,
                        temperature=decode_temperature,
                        chunk_length=config.WHISPER_CHUNK_LENGTH,
                        condition_on_previous_text=condition_on_previous_text,
                        initial_prompt=context_prompt.strip() if context_prompt else None,
                        video_crf=video_crf,
                        audio_copy=None,
                        generate_social_copy=True,
                        use_llm_social_copy=use_llm,
                        llm_model=llm_model,
                        llm_temperature=0.6,
                        llm_api_key=api_key,
                        artifact_dir=artifact_dir,
                        use_hw_accel=(platform.system() == "Darwin" and config.USE_HW_ACCEL),
                        progress_callback=update_progress,
                    )

                    # Handle Result
                    processed_path: Path
                    social: SocialCopy
                    if isinstance(result, tuple):
                        processed_path, social = result
                    else:
                        processed_path = result
                        social = None # type: ignore

                    # Update State
                    st.session_state["processed_path"] = str(processed_path)
                    st.session_state["social"] = social
                    st.session_state["artifact_dir"] = str(artifact_dir)
                    st.session_state["processed_video_bytes"] = processed_path.read_bytes()
                    st.session_state["processed_video_name"] = processed_path.name
                    st.session_state["processing_done"] = True
                    
                    # Load artifacts
                    transcript_file = artifact_dir / "transcript.txt"
                    if transcript_file.exists():
                        st.session_state["transcript_bytes"] = transcript_file.read_bytes()
                    
                    social_json = artifact_dir / "social_copy.json"
                    if social_json.exists():
                        st.session_state["social_json_bytes"] = social_json.read_bytes()

                    # History
                    if user:
                        _record_processing_history(
                            user, uploaded.name, processed_path, artifact_dir, 
                            {"model": model_size, "crf": video_crf, "llm": use_llm}
                        )

                    st.toast("Processing Complete!", icon="✅")
                    st.rerun() # Refresh to show results cleanly

                except Exception as exc:
                     _log_ui_error(exc)
                     st.error(f"Processing Failed: {exc}")


            # --- RESULTS ACTIONS ---
            if is_processed:
                st.markdown("#### Downloads")
                col_d1, col_d2 = st.columns(2)
                with col_d1:
                    if "processed_video_bytes" in st.session_state:
                         st.download_button("Download Video", data=st.session_state["processed_video_bytes"], file_name=st.session_state["processed_video_name"], mime="video/mp4", use_container_width=True)
                with col_d2:
                     if "transcript_bytes" in st.session_state:
                         st.download_button("Download Text", data=st.session_state["transcript_bytes"], file_name="transcript.txt", mime="text/plain", use_container_width=True, type="secondary")
                
                # Social Copy Section
                if st.session_state.get("social"):
                    st.markdown("---")
                    render_social_copy(st.session_state["social"])
                
                # TikTok Upload
                st.markdown("---")
                tiktok_tokens = _get_tiktok_tokens()
                if not tiktok_tokens:
                     if st.button("Connect TikTok", type="secondary", use_container_width=True):
                         # ... (reuse oauth logic basically) ...
                         # Since this is a complex logic block, let's keep it simple here.
                         state = f"tiktok-{secrets.token_hex(8)}"
                         st.session_state["tiktok_oauth_state"] = state
                         st.session_state["tiktok_auth_url"] = tiktok.build_auth_url(tiktok.config_from_env(), state=state)
                         st.rerun()
                     
                     if st.session_state.get("tiktok_auth_url"):
                         st.markdown(f"[Click to Authorize TikTok]({st.session_state['tiktok_auth_url']})")

                else:
                    if st.button("Upload to TikTok", type="primary", use_container_width=True):
                        try:
                            tt_title = st.session_state["social"].tiktok.title if st.session_state.get("social") else "Video"
                            title_val = st.session_state.get("tt_title", tt_title)
                            desc_val = st.session_state.get("tt_desc", "")
                            
                            path = Path(st.session_state["processed_path"])
                            tiktok.upload_video(tiktok_tokens, path, title_val, desc_val)
                            st.success("Uploaded to TikTok!")
                            _record_tiktok_history(user, {"status": "success"})
                        except Exception as e:
                            st.error(f"TikTok Upload Failed: {e}")
    
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

# Legacy Streamlit UI Notes

The first version of the product shipped as a Streamlit dashboard. The code has been removed, but the concepts live here so we can resurrect or adapt them later.

## Page + layout patterns
- Used `st.set_page_config` for wide layout, "Greek Sub Publisher" title, and 🇬🇷 emoji favicon.
- Custom CSS (in `styles.css`) styled expanders and typography to keep subtitles/timeline controls compact.
- Sidebar header showed brand badge + session info; main header showed dashboard stats via `render_stat_card` helpers.
- Upload hero encouraged drag-and-drop for vertical videos, with preset buttons for processing speed/quality toggles.

## Session and auth handling
- Sessions were persisted with `extra_streamlit_components.CookieManager` to keep users signed in for 30 days.
- `_persist_session` stored both `session_state` entries and a browser cookie; `_current_user` restored from cookie or session data.
- Google OAuth callbacks relied on URL query params (`auth_token`, `code`) and were cleared after use via `_clear_query_params`.
- TikTok OAuth + upload ran inline after processing so creators could publish without leaving the app.

## Secrets + configuration
- Streamlit secrets were read from `.streamlit/secrets.toml` with an optional `GSP_SECRETS_FILE` override.
- AI defaults (LLM model, temperature, auto-enable toggle) were loaded from `.streamlit/app_settings.toml` via `_load_ai_settings`.
- `_resolve_openai_api_key` preferred `OPENAI_API_KEY` env, then `st.secrets`, and disabled AI UI affordances when absent.

## Metrics + resilience
- `_log_ui_error` wrapped pipeline errors before sending them to `metrics.log_pipeline_metrics` for auditing.
- `_should_autorun` used `st.runtime.exists()` to auto-trigger processing when the UI ran inside Streamlit.
- Upload handling cleared cached outputs via `_clear_processing_state` to avoid stale subtitles between runs.

## Reuse ideas later
- Keep the metric cards + quick processing presets—they worked well for non-technical users.
- Cookie-backed auth and inline OAuth callbacks made "open and create" flows nearly instant.
- Consider reusing the app settings TOML convention for per-deployment defaults if we need lightweight configuration again.

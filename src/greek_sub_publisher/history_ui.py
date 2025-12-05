"""UI components for viewing user history ("My Library")."""

from __future__ import annotations

import pandas as pd
import streamlit as st

from . import auth, history


def render_library_page(user: auth.User, history_store: history.HistoryStore) -> None:
    """Render the "My Library" view with a sortable data table."""
    st.markdown("## 📚 My Library")
    st.caption("A record of your recent processing and publishing activity.")

    # Fetch recent events
    events = history_store.recent_for_user(user, limit=50)

    if not events:
        st.info("No activity found. Start processing videos to build your library!")
        return

    # Convert to DataFrame for easy display
    data = []
    for evt in events:
        details = evt.data.copy()
        # Flatten some common details for the table
        model_size = details.pop("model_size", "")
        video_crf = details.pop("video_crf", "")
        
        row = {
            "Time": evt.ts,
            "Activity": evt.kind.replace("_", " ").title(),
            "Summary": evt.summary,
            "Model": model_size,
            "Quality": f"CRF {video_crf}" if video_crf else "",
        }
        data.append(row)

    df = pd.DataFrame(data)
    
    # Beautify timestamp
    try:
        df["Time"] = pd.to_datetime(df["Time"]).dt.strftime("%Y-%m-%d %H:%M")
    except Exception:
        pass

    st.dataframe(
        df,
        use_container_width=True,
        hide_index=True,
        column_config={
            "Time": st.column_config.TextColumn("Date & Time", width="medium"),
            "Activity": st.column_config.TextColumn("Type", width="small"),
            "Summary": st.column_config.TextColumn("Description", width="large"),
            "Model": st.column_config.TextColumn("Model", width="small"),
            "Quality": st.column_config.TextColumn("Quality", width="small"),
        },
    )

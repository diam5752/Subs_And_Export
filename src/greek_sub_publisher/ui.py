from pathlib import Path
import streamlit as st
from greek_sub_publisher.subtitles import SocialCopy

def load_css(file_path: Path) -> None:
    """Injects CSS from a file into the Streamlit app."""
    with open(file_path) as f:
        st.markdown(f"<style>{f.read()}</style>", unsafe_allow_html=True)

def render_sidebar_header() -> None:
    """Renders the sidebar branding."""
    st.markdown(
        """
        <div style="padding-bottom: 20px; border-bottom: 1px solid #27272a; margin-bottom: 20px;">
            <div style="font-weight: 600; font-size: 16px; color: #fff; display: flex; align-items: center; gap: 8px;">
                <span style="background: #5e6ad2; width: 20px; height: 20px; border-radius: 4px; display: inline-block;"></span>
                Greek Sub Publisher
            </div>
            <div style="font-size: 12px; color: #71717a; margin-top: 4px;">v2.1.0 &bull; Enterprise</div>
        </div>
        """,
        unsafe_allow_html=True,
    )

def render_dashboard_header() -> None:
    """Renders the main dashboard header."""
    st.markdown(
        """
        <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 24px;">
            <div>
                <h1 style="margin: 0;">Dashboard</h1>
                <div style="color: #a1a1aa; font-size: 13px;">Manage your video processing pipeline.</div>
            </div>
            <div style="display: flex; gap: 12px;">
                <div style="display: flex; align-items: center; gap: 6px; font-size: 12px; color: #a1a1aa; background: #18181b; padding: 6px 12px; border-radius: 20px; border: 1px solid #27272a;">
                    <span class="status-dot"></span> System Operational
                </div>
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )

def render_stat_card(label: str, value: str) -> None:
    """Renders a metric card."""
    st.markdown(
        f"""
        <div class="dashboard-card">
            <div class="stat-label">{label}</div>
            <div class="stat-value">{value}</div>
        </div>
        """,
        unsafe_allow_html=True,
    )

def render_social_copy(social: SocialCopy) -> None:
    """Renders the social copy in a technical tabbed interface."""
    st.markdown("### Social Intelligence")
    
    tabs = st.tabs(["TikTok", "Shorts", "Reels"])

    with tabs[0]:
        st.text_input("Title", value=social.tiktok.title, key="tt_title")
        st.text_area("Description", value=social.tiktok.description, height=150, key="tt_desc")

    with tabs[1]:
        st.text_input("Title", value=social.youtube_shorts.title, key="yt_title")
        st.text_area("Description", value=social.youtube_shorts.description, height=150, key="yt_desc")

    with tabs[2]:
        st.text_input("Title", value=social.instagram.title, key="ig_title")
        st.text_area("Description", value=social.instagram.description, height=150, key="ig_desc")

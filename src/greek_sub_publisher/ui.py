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
        <div style="padding-bottom: 24px; border-bottom: 1px solid #27272a; margin-bottom: 24px;">
            <div style="font-weight: 600; font-size: 18px; color: #fff; display: flex; align-items: center; gap: 10px;">
                <div style="background: linear-gradient(135deg, #6366f1 0%, #4f46e5 100%); width: 24px; height: 24px; border-radius: 6px; display: flex; align-items: center; justify-content: center; box-shadow: 0 2px 4px rgba(99, 102, 241, 0.3);">
                    <span style="color: white; font-size: 14px; font-weight: 700;">G</span>
                </div>
                Greek Sub Publisher
            </div>
            <div style="font-size: 12px; color: #71717a; margin-top: 6px; font-weight: 500;">v2.2.0 &bull; Enterprise Edition</div>
        </div>
        """,
        unsafe_allow_html=True,
    )

def render_dashboard_header() -> None:
    """Renders the main dashboard header."""
    st.markdown(
        """
        <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 32px;">
            <div>
                <h1 style="margin: 0; font-size: 28px; letter-spacing: -0.02em;">Dashboard</h1>
                <div style="color: #a1a1aa; font-size: 14px; margin-top: 4px;">Manage your video processing pipeline and social exports.</div>
            </div>
            <div style="display: flex; gap: 12px;">
                <div style="display: flex; align-items: center; gap: 8px; font-size: 12px; color: #a1a1aa; background: #121214; padding: 8px 16px; border-radius: 20px; border: 1px solid #27272a; font-weight: 500;">
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

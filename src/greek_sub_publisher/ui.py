from pathlib import Path
import streamlit as st
from greek_sub_publisher.subtitles import SocialCopy

def load_css(file_path: Path) -> None:
    """Injects CSS from a file into the Streamlit app."""
    with open(file_path) as f:
        st.markdown(f"<style>{f.read()}</style>", unsafe_allow_html=True)

def render_sidebar_header() -> None:
    """Renders the minimalist sidebar branding."""
    st.markdown(
        """
        <div style="padding-bottom: 20px; margin-bottom: 20px; border-bottom: 1px solid rgba(255,255,255,0.1);">
            <div style="font-weight: 600; font-size: 15px; color: #fff; display: flex; align-items: center; gap: 12px;">
                <div style="background: #10a37f; width: 24px; height: 24px; border-radius: 6px; display: flex; align-items: center; justify-content: center;">
                    <span style="color: white; font-size: 14px; font-weight: 700;">G</span>
                </div>
                Greek Sub Publisher
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def render_dashboard_header() -> None:
    """Renders the main dashboard header/title."""
    st.markdown(
        """
        <div style="margin-bottom: 32px;">
            <h1 style="font-size: 32px; font-weight: 700; letter-spacing: -0.03em; margin-bottom: 8px;">Studio</h1>
            <p style="color: #8e8e8e; font-size: 15px;">Create stunning subtitles for your videos</p>
        </div>
        """,
        unsafe_allow_html=True,
    )


def render_stat_card(label: str, value: str, icon: str = "") -> None:
    """Renders a statistics card for the dashboard."""
    st.markdown(
        f"""
        <div class="dashboard-card">
            <div class="stat-label">{icon} {label}</div>
            <div class="stat-value">{value}</div>
        </div>
        """,
        unsafe_allow_html=True,
    )

def render_upload_hero() -> None:
    """Renders a large, Apple-style upload hero section."""
    st.markdown(
        """
        <div style="text-align: center; margin-top: 40px; margin-bottom: 20px;">
            <h1 style="font-size: 48px; letter-spacing: -0.03em; margin-bottom: 16px;">Create stunning subtitles.</h1>
            <p style="font-size: 18px; color: #8e8e93; max-width: 600px; margin: 0 auto;">
                Upload your vertical video. We'll handle the transcription, styling, and social intelligence.
            </p>
        </div>
        """,
        unsafe_allow_html=True,
    )

def render_studio_layout(
    video_path: str | None = None, 
    video_bytes: bytes | None = None,
    processing_done: bool = False
) -> None:
    """
    Renders the 2-column studio layout.
    This function sets up the grid, but the caller must populate the columns 
    using the returned context managers or by accessing the layout.
    
    Since Streamlit containers aren't passed around easily as objects to 'populate' later 
    in a clean way without context managers, this function mainly serves to 
    set the visual stage or returns column objects.
    """
    pass # Logic moved to app.py generic usage, this is a placeholder if needed for complex HTML injection.


def render_social_copy(social: SocialCopy) -> None:
    """Renders the social copy in a clean, technical tabbed interface."""
    st.markdown("### Social Intelligence")
    
    tabs = st.tabs(["TikTok", "Shorts", "Reels"])

    with tabs[0]:
        st.caption("Optimized for TikTok algorithm")
        st.text_input("Title", value=social.tiktok.title, key="tt_title")
        st.text_area("Description", value=social.tiktok.description, height=120, key="tt_desc")

    with tabs[1]:
        st.caption("Optimized for YouTube SEO")
        st.text_input("Title", value=social.youtube_shorts.title, key="yt_title")
        st.text_area("Description", value=social.youtube_shorts.description, height=120, key="yt_desc")

    with tabs[2]:
        st.caption("Optimized for Instagram engagement")
        st.text_input("Title", value=social.instagram.title, key="ig_title")
        st.text_area("Description", value=social.instagram.description, height=120, key="ig_desc")

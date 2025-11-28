from greek_sub_publisher import subtitles


def test_build_social_copy_returns_platform_specific_strings() -> None:
    transcript = "Coding tips coding flow python python testing coffee rituals for focus."

    social = subtitles.build_social_copy(transcript)

    assert social.tiktok.title.startswith("Coding & Python")
    assert "Follow for daily Greek clips." in social.tiktok.description
    assert "#coding" in social.youtube_shorts.description
    assert social.instagram.title.endswith("Instagram Reels")
    assert "#reels" in social.instagram.description

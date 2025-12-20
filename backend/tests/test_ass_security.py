from backend.app.services import subtitles


def test_sanitize_ass_text_removes_newlines():
    """Verify that newlines are removed to prevent ASS injection."""
    malicious = "Hello\nDialogue: 0,0:00:00.00,0:00:05.00,Default,,0,0,0,,Injected!"
    sanitized = subtitles.subtitle_renderer.sanitize_ass_text(malicious)

    assert "\n" not in sanitized
    assert "\r" not in sanitized
    assert "Hello Dialogue:" in sanitized
    assert "Injected!" in sanitized

def test_create_styled_subtitle_file_resists_injection(tmp_path):
    """Verify that injected content does not appear as a new line in the generated file."""
    # We use a payload that fits on one line but contains a newline injection
    malicious_text = "Hello\nDialogue: 0,0:00:00.00,0:00:01.00,Default,,0,0,0,,Hacked"

    cue = subtitles.Cue(start=0.0, end=1.0, text=malicious_text)

    srt_path = tmp_path / "test.srt"
    srt_path.write_text("1\n00:00:00,000 --> 00:00:01,000\nDummy", encoding="utf-8")

    # We generate the ASS file
    ass_path = subtitles.create_styled_subtitle_file(
        srt_path,
        cues=[cue],
        output_dir=tmp_path,
        max_lines=2
    )

    content = ass_path.read_text(encoding="utf-8")

    # Check that we don't have the injected line as a functional Dialogue line
    # The sanitizer should turn \n into space
    # So we expect: "Dialogue: ...,Hello Dialogue: ... Hacked" (on one line)

    lines = content.splitlines()
    injected_lines = [
        line for line in lines
        if line.strip() == "Dialogue: 0,0:00:00.00,0:00:01.00,Default,,0,0,0,,Hacked"
    ]

    assert not injected_lines, "Found injected Dialogue line in ASS file!"

    # Verify the content is there but sanitized
    assert "Hello Dialogue:" in content
    assert "Hacked" in content

def test_sanitize_ass_text_removes_tags():
    """Verify that ASS override tags are neutralized."""
    malicious = "Hello {\\c&H0000FF&}World"
    sanitized = subtitles.subtitle_renderer.sanitize_ass_text(malicious)

    assert "{" not in sanitized
    assert "}" not in sanitized
    assert "\\" not in sanitized
    # Expect replacements
    assert "(" in sanitized
    assert ")" in sanitized
    assert "/" in sanitized

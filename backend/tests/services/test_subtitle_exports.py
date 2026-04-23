import json
from pathlib import Path

import pytest

from backend.app.services import subtitle_exports

FIXTURE_ROOT = Path(__file__).resolve().parents[3] / "testdata" / "subtitles"


def test_prepare_delivery_cues_matches_greek_preview_contract():
    # REGRESSION: SRT/VTT/TXT exports must segment the same Greek delivery cue
    # shape as the frontend preview for the UI percentage scale.
    cues = subtitle_exports.prepare_delivery_cues(
        subtitle_exports.read_transcript_cues(FIXTURE_ROOT / "greek_long_cue.json"),
        max_subtitle_lines=2,
        subtitle_size=85,
    )

    assert [cue.text for cue in cues] == [
        "ΓΕΙΑ ΣΑΣ,",
        "ΜΕ ΛΕΝΕ ΙΑΝΝΗ.",
        "ΕΙΜΑΙ ΑΠΟ ΤΗΝ ΑΜΕΡΙΚΗ.",
        "Ο ΠΑΤΕΡΑΣ ΜΟΥ ΕΙΝΑΙ ΑΠΟ ΤΗΝ ΜΑΚΕΔΟΝΙΑ, ΣΕΡΡΕΣ,",
        "ΑΛΛΑ Ο ΠΑΠΠΟΥΣ ΜΟΥ ΚΑΙ Η ΓΙΑΓΙΑ ΜΟΥ ΗΤΑΝ ΠΡΟΣΦΥΓΕΣ",
        "ΑΠΟ ΤΗΝ ΘΡΑΚΗ.",
    ]
    assert cues[-1].end == 15.0


def test_export_subtitle_file_writes_standard_srt_timestamp(tmp_path: Path):
    transcript = tmp_path / "transcription.json"
    transcript.write_text(
        json.dumps([{"start": 0.5, "end": 1.5, "text": "Hello world"}]),
        encoding="utf-8",
    )
    export_path = tmp_path / "processed.srt"

    result = subtitle_exports.export_subtitle_file(
        transcription_json=transcript,
        export_path=export_path,
        export_format="srt",
        max_subtitle_lines=2,
        subtitle_size=100,
    )

    assert result.content_type == "application/x-subrip"
    assert export_path.read_text(encoding="utf-8").startswith(
        "1\n00:00:00,500 --> 00:00:01,500\nHello world"
    )


@pytest.mark.parametrize(
    "payload",
    [
        {"start": 0, "end": 1, "text": "not a list"},
        [{"start": "bad", "end": 1, "text": "bad start"}],
        [{"start": 0, "end": 0, "text": "zero duration"}],
        [{"start": 0, "end": 1, "text": "bad word", "words": [{"start": 0, "end": 0, "text": "x"}]}],
    ],
)
def test_read_transcript_cues_rejects_malformed_payloads(tmp_path: Path, payload):
    transcript = tmp_path / "transcription.json"
    transcript.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(subtitle_exports.MalformedTranscriptError):
        subtitle_exports.read_transcript_cues(transcript)

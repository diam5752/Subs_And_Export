from fastapi.testclient import TestClient


def test_transcription_engine_catalog_requires_authentication(client: TestClient) -> None:
    response = client.get("/videos/transcription-engines")

    assert response.status_code == 401


def test_transcription_engine_catalog_exposes_capabilities(
    client: TestClient,
    user_auth_headers: dict[str, str],
) -> None:
    response = client.get("/videos/transcription-engines", headers=user_auth_headers)

    assert response.status_code == 200
    payload = response.json()
    assert payload[0] == {
        "id": "mock-studio",
        "tier": "standard",
        "provider": "mock",
        "model": "mock-caption-v1",
        "label": "Demo studio",
        "description": "Deterministic word-timed captions for testing the complete product with zero provider calls.",
        "privacy": "local",
        "supports_word_timestamps": True,
        "supports_diarization": False,
        "supports_realtime": False,
        "caption_ready": True,
        "recommended": False,
        "available": False,
        "cost_usd_per_hour": 0.0,
        "limitations": ["Transcript text is simulated while mock mode is enabled."],
    }
    assert any(
        item["id"] == "local-private" and item["available"] is True
        for item in payload
    )
    assert any(
        item["id"] == "openai-diarized"
        and item["supports_diarization"] is True
        and item["caption_ready"] is False
        for item in payload
    )
    assert any(
        item["id"] == "elevenlabs-scribe-v2"
        and item["model"] == "scribe_v2"
        and item["available"] is False
        and item["recommended"] is False
        and item["cost_usd_per_hour"] == 0.22
        for item in payload
    )

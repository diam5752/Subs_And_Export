from backend.tests.process_stream import post_process_stream


def test_process_video_resolution_length_limit(client, user_auth_headers):
    """
    Sentinel: Test that excessively long video_resolution string is rejected.
    """
    long_string = "a" * 1000

    response = post_process_stream(
        client,
        user_auth_headers,
        filename="test_video.mp4",
        content=b"fake content",
        metadata={"video_resolution": long_string},
    )

    assert response.status_code == 400
    assert response.json()["detail"] == "Invalid upload metadata"


def test_process_provider_length_limit(client, user_auth_headers):
    long_string = "a" * 1000

    response = post_process_stream(
        client,
        user_auth_headers,
        filename="test_video.mp4",
        content=b"fake content",
        metadata={"transcribe_provider": long_string},
    )

    assert response.status_code == 400
    assert response.json()["detail"] == "Invalid upload metadata"


def test_process_openai_model_length_limit(client, user_auth_headers):
    long_string = "a" * 1000

    response = post_process_stream(
        client,
        user_auth_headers,
        filename="test_video.mp4",
        content=b"fake content",
        metadata={"openai_model": long_string},
    )

    assert response.status_code == 400
    assert response.json()["detail"] == "Invalid upload metadata"


def test_process_highlight_style_length_limit(client, user_auth_headers):
    """
    Sentinel: Test that excessively long highlight_style string is rejected.
    """
    long_string = "a" * 1000

    response = post_process_stream(
        client,
        user_auth_headers,
        filename="test_video.mp4",
        content=b"fake content",
        metadata={"highlight_style": long_string},
    )

    assert response.status_code == 400
    assert response.json()["detail"] == "Invalid upload metadata"

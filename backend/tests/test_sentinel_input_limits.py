
def test_process_video_resolution_length_limit(client, user_auth_headers):
    """
    Sentinel: Test that excessively long video_resolution string is rejected.
    """
    long_string = "a" * 1000

    response = client.post(
        "/videos/process",
        headers=user_auth_headers,
        files={"file": ("test_video.mp4", b"fake content", "video/mp4")},
        data={
            "video_resolution": long_string
        }
    )

    assert response.status_code == 400
    assert "Resolution string too long" in response.json()["detail"]

def test_process_provider_length_limit(client, user_auth_headers):
    long_string = "a" * 1000

    response = client.post(
        "/videos/process",
        headers=user_auth_headers,
        files={"file": ("test_video.mp4", b"fake content", "video/mp4")},
        data={
            "transcribe_provider": long_string
        }
    )

    assert response.status_code == 400
    assert "Provider name too long" in response.json()["detail"]

def test_process_openai_model_length_limit(client, user_auth_headers):
    long_string = "a" * 1000

    response = client.post(
        "/videos/process",
        headers=user_auth_headers,
        files={"file": ("test_video.mp4", b"fake content", "video/mp4")},
        data={
            "openai_model": long_string
        }
    )

    assert response.status_code == 400
    assert "OpenAI model name too long" in response.json()["detail"]

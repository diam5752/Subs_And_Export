
import os
from unittest.mock import patch


def test_cleanup_endpoint_security(client, user_auth_headers):
    """
    Test security controls on the cleanup endpoint.
    """
    # 1. Unauthenticated request -> 401 Unauthorized
    resp = client.post("/videos/jobs/cleanup?days=30")
    assert resp.status_code == 401

    # 2. Authenticated but NOT admin -> 403 Forbidden
    # user_auth_headers is for "test@example.com" (from conftest.py)
    # Ensure environment does NOT have this email as admin
    with patch.dict(os.environ, {"GSP_ADMIN_EMAILS": ""}):
        resp = client.post("/videos/jobs/cleanup?days=30", headers=user_auth_headers)
        assert resp.status_code == 403
        assert resp.json()["detail"] == "Admin access not configured"

    with patch.dict(os.environ, {"GSP_ADMIN_EMAILS": "admin@example.com"}):
        resp = client.post("/videos/jobs/cleanup?days=30", headers=user_auth_headers)
        assert resp.status_code == 403
        assert resp.json()["detail"] == "Not authorized"

    # 3. Authenticated AND Admin -> 200 OK
    # We need to make the user email match the admin email.
    # The default user is test@example.com (from conftest.py).
    with patch.dict(os.environ, {"GSP_ADMIN_EMAILS": "test@example.com"}):
        resp = client.post("/videos/jobs/cleanup?days=30", headers=user_auth_headers)
        assert resp.status_code == 200
        assert "deleted_count" in resp.json()

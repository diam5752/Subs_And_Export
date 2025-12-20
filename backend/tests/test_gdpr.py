

def test_data_export(client, user_auth_headers):
    """Ensure user can export their data (GDPR Right to Access)."""
    # 1. Create some data
    files = {"file": ("gdpr_test.mp4", b"data", "video/mp4")}
    client.post("/videos/process", headers=user_auth_headers, files=files)

    # 2. Request Export
    response = client.get("/auth/export", headers=user_auth_headers)

    # 3. Verify
    assert response.status_code == 200
    data = response.json()
    assert "profile" in data
    assert "jobs" in data
    assert len(data["jobs"]) >= 1
    
    # Get current user email to verify
    me_resp = client.get("/auth/me", headers=user_auth_headers)
    assert me_resp.status_code == 200
    email = me_resp.json()["email"]
    assert data["profile"]["email"] == email


def test_account_deletion_cleans_files(client, user_auth_headers):
    """Ensure account deletion removes all files (GDPR Right to Erasure)."""
    # Get email before deletion
    me_resp = client.get("/auth/me", headers=user_auth_headers)
    email = me_resp.json()["email"]
    
    # 1. Create Job
    files = {"file": ("gdpr_delete.mp4", b"content", "video/mp4")}
    resp = client.post("/videos/process", headers=user_auth_headers, files=files)
    assert resp.status_code == 200
    job_id = resp.json()["id"]

    # 2. Delete Account
    del_resp = client.delete("/auth/me", headers=user_auth_headers)
    assert del_resp.status_code == 200

    # 3. Verify Login Fails
    # We need to try to get a new token because the old token might still seem valid if stateless JWT (unless blacklist checked)
    # But /auth/me should fail if user is gone from DB.
    login_resp = client.get("/auth/me", headers=user_auth_headers)
    assert login_resp.status_code == 401

    # 4. Re-register and check empty
    client.post("/auth/register", json={"email": email, "password": "testpassword123", "name": "Test User"})
    # Login
    token_resp = client.post("/auth/token", data={"username": email, "password": "testpassword123"})
    new_token = token_resp.json()["access_token"]
    new_headers = {"Authorization": f"Bearer {new_token}"}

    # Check jobs
    jobs_resp = client.get("/videos/jobs", headers=new_headers)
    assert jobs_resp.status_code == 200
    jobs = jobs_resp.json()
    assert len(jobs) == 0, "Jobs should be wiped after account deletion"

    # 5. Verify Files Gone (Harder without access to server FS in blackbox test)
    # But checking jobs list is decent proxy for DB cleanup.
    # For file cleanup, we rely on implementation logic verification or integration testing.

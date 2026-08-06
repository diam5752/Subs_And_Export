from __future__ import annotations

import threading
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient

from backend.app.api.endpoints import intelligence_routes, job_routes
from backend.app.core.config import settings
from backend.app.core.database import Database
from backend.app.core.workspace_deletion import delete_job_workspace
from backend.app.services import account_erasure
from backend.app.services.fact_checking import FactCheckResult
from backend.app.services.jobs import JobStore
from backend.app.services.social_intelligence import SocialContent, SocialCopy


@pytest.mark.parametrize("intelligence_action", ["fact-check", "social-copy"])
@pytest.mark.parametrize("deletion_kind", ["job", "account"])
def test_delete_waits_for_in_flight_intelligence_provider(
    intelligence_action: str,
    deletion_kind: str,
    client: TestClient,
    funded_user_auth_headers: dict[str, str],
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Erasure cannot finish while transcript-derived provider work is live."""
    data_dir = tmp_path / f"intelligence-{intelligence_action}-{deletion_kind}"
    artifacts_root = data_dir / "artifacts"
    uploads_dir = data_dir / "uploads"
    artifacts_root.mkdir(parents=True)
    uploads_dir.mkdir(parents=True)
    monkeypatch.setattr(settings, "data_dir", data_dir)
    monkeypatch.setattr(settings, "mock_external_services", False)

    user_id = client.get(
        "/auth/me",
        headers=funded_user_auth_headers,
    ).json()["id"]
    job_id = f"intelligence-delete-race-{uuid.uuid4().hex}"
    job_store = JobStore(Database())
    job_store.create_job(job_id, user_id)
    job_store.update_job(job_id, status="completed", progress=100)
    artifact_dir = artifacts_root / job_id
    artifact_dir.mkdir()
    (artifact_dir / "transcript.txt").write_text(
        "private transcript that must remain protected during provider work",
        encoding="utf-8",
    )

    provider_entered = threading.Event()
    allow_provider = threading.Event()
    delete_reached_erasure = threading.Event()
    reservation = MagicMock()

    def reserve_charge_stub(**_kwargs: object) -> tuple[MagicMock, int]:
        return reservation, 1_000

    monkeypatch.setattr(
        intelligence_routes,
        "reserve_llm_charge",
        reserve_charge_stub,
    )

    if intelligence_action == "fact-check":

        def blocked_fact_check_provider(
            *_args: object,
            **_kwargs: object,
        ) -> FactCheckResult:
            provider_entered.set()
            assert allow_provider.wait(timeout=5)
            return FactCheckResult(
                truth_score=100,
                supported_claims_pct=100,
                claims_checked=0,
                items=[],
            )

        monkeypatch.setattr(
            intelligence_routes,
            "generate_fact_check",
            blocked_fact_check_provider,
        )
    else:

        def blocked_social_copy_provider(
            *_args: object,
            **_kwargs: object,
        ) -> SocialCopy:
            provider_entered.set()
            assert allow_provider.wait(timeout=5)
            return SocialCopy(
                generic=SocialContent(
                    title_el="Ασφαλής τίτλος",
                    title_en="Safe title",
                    description_el="Ασφαλής περιγραφή",
                    description_en="Safe description",
                    hashtags=["#safe"],
                ),
            )

        monkeypatch.setattr(
            intelligence_routes,
            "build_social_copy_llm",
            blocked_social_copy_provider,
        )

    if deletion_kind == "account":
        def mark_account_delete_workspace(
            *,
            job_id: str,
            uploads_dir: Path,
            artifacts_dir: Path,
            expected_user_id: str,
        ) -> None:
            delete_reached_erasure.set()
            delete_job_workspace(
                job_id=job_id,
                uploads_dir=uploads_dir,
                artifacts_dir=artifacts_dir,
                expected_user_id=expected_user_id,
            )

        monkeypatch.setattr(
            account_erasure,
            "delete_job_workspace",
            mark_account_delete_workspace,
        )
    else:
        def mark_job_delete_workspace(
            *,
            job_id: str,
            uploads_dir: Path,
            artifacts_dir: Path,
            expected_user_id: str,
        ) -> None:
            delete_reached_erasure.set()
            delete_job_workspace(
                job_id=job_id,
                uploads_dir=uploads_dir,
                artifacts_dir=artifacts_dir,
                expected_user_id=expected_user_id,
            )

        monkeypatch.setattr(
            job_routes,
            "delete_job_workspace",
            mark_job_delete_workspace,
        )

    try:
        with ThreadPoolExecutor(max_workers=2) as executor:
            intelligence_request = executor.submit(
                client.post,
                f"/videos/jobs/{job_id}/{intelligence_action}",
                headers=funded_user_auth_headers,
            )
            assert provider_entered.wait(timeout=5)
            if deletion_kind == "account":
                delete_request = executor.submit(
                    client.delete,
                    "/auth/me",
                    headers=funded_user_auth_headers,
                )
            else:
                delete_request = executor.submit(
                    client.delete,
                    f"/videos/jobs/{job_id}",
                    headers=funded_user_auth_headers,
                )

            try:
                assert not delete_reached_erasure.wait(timeout=0.5)
            finally:
                allow_provider.set()

            intelligence_response = intelligence_request.result(timeout=5)
            delete_response = delete_request.result(timeout=5)

        assert intelligence_response.status_code == 200, intelligence_response.text
        assert delete_response.status_code == 200, delete_response.text
        assert delete_response.json()["status"] == "deleted"
        assert job_store.get_job(job_id) is None
        assert not artifact_dir.exists()
    finally:
        allow_provider.set()

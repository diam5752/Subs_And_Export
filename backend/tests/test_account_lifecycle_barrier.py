from __future__ import annotations

import hashlib
import threading
import uuid
from pathlib import Path

import pytest
from fastapi import HTTPException
from starlette.requests import Request

from backend.app.api.deps import get_current_user_with_media_lifecycle
from backend.app.core.auth import UserStore
from backend.app.core.config import settings
from backend.app.core.database import Database
from backend.app.core.erasure_journal import ErasureJournal
from backend.app.core.workspace_deletion import (
    AccountLifecycleLockTimeoutError,
    lock_account_lifecycle,
)
from backend.app.services.account_erasure import (
    ActiveAccountJobsError,
    erase_account_and_media,
)
from backend.app.services.billing import BillingService
from backend.app.services.jobs import JobStore
from backend.app.services.points import PointsStore


def test_account_lifecycle_shared_lock_blocks_exclusive_erasure(tmp_path: Path) -> None:
    user_id = "shared-writer"
    result: list[str] = []

    def try_exclusive() -> None:
        try:
            with lock_account_lifecycle(
                data_dir=tmp_path,
                user_id=user_id,
                shared=False,
                timeout_seconds=0.1,
            ):
                result.append("acquired")
        except AccountLifecycleLockTimeoutError:
            result.append("blocked")

    with lock_account_lifecycle(
        data_dir=tmp_path,
        user_id=user_id,
        shared=True,
    ):
        contender = threading.Thread(target=try_exclusive)
        contender.start()
        contender.join(timeout=2)
        assert not contender.is_alive()

    assert result == ["blocked"]
    lock_dir = tmp_path / ".account-locks"
    assert lock_dir.stat().st_mode & 0o777 == 0o700
    assert all(item.stat().st_mode & 0o777 == 0o600 for item in lock_dir.iterdir())


def test_account_lifecycle_locks_do_not_collide_between_users(tmp_path: Path) -> None:
    first_user_id = "shared-writer"
    legacy_stripe = (
        int.from_bytes(
            hashlib.sha256(first_user_id.encode("utf-8")).digest()[:2],
            byteorder="big",
        )
        % 256
    )
    colliding_user_id = next(
        candidate
        for index in range(1, 10_000)
        if (
            candidate := f"other-user-{index}"
        )
        and int.from_bytes(
            hashlib.sha256(candidate.encode("utf-8")).digest()[:2],
            byteorder="big",
        )
        % 256
        == legacy_stripe
    )

    with lock_account_lifecycle(
        data_dir=tmp_path,
        user_id=first_user_id,
        shared=True,
    ):
        with lock_account_lifecycle(
            data_dir=tmp_path,
            user_id=colliding_user_id,
            shared=False,
            timeout_seconds=0.1,
        ):
            pass


def test_account_erasure_waits_for_admitted_writer_and_observes_its_job(
    tmp_path: Path,
) -> None:
    db = Database()
    user_store = UserStore(db=db)
    user = user_store.register_local_user(
        f"lifecycle-{uuid.uuid4().hex}@example.com",
        "testpassword123",
        "Lifecycle",
    )
    points_store = PointsStore(db=db)
    job_store = JobStore(db=db)
    journal = ErasureJournal(tmp_path / "journal", retention_days=30)
    journal.initialize()
    finished = threading.Event()
    errors: list[BaseException] = []

    def erase() -> None:
        try:
            erase_account_and_media(
                db=db,
                billing_service=BillingService(db=db, points_store=points_store),
                user_store=user_store,
                user_id=user.id,
                data_dir=tmp_path,
                journal=journal,
            )
        except BaseException as exc:
            errors.append(exc)
        finally:
            finished.set()

    with lock_account_lifecycle(
        data_dir=tmp_path,
        user_id=user.id,
        shared=True,
    ):
        eraser = threading.Thread(target=erase)
        eraser.start()
        assert not finished.wait(0.15)
        job = job_store.create_job(f"admitted-{uuid.uuid4().hex}", user.id)

    eraser.join(timeout=3)
    assert not eraser.is_alive()
    assert len(errors) == 1
    assert isinstance(errors[0], ActiveAccountJobsError)
    assert user_store.get_user_by_id(user.id) is not None
    assert job_store.get_job(job.id) is not None


def test_stale_authenticated_writer_is_rejected_after_erasure_wins(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    db = Database()
    user_store = UserStore(db=db)
    user = user_store.register_local_user(
        f"stale-writer-{uuid.uuid4().hex}@example.com",
        "testpassword123",
        "Stale Writer",
    )
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    result: list[BaseException | str] = []
    request = Request(
        {
            "type": "http",
            "method": "GET",
            "path": "/videos/jobs",
            "headers": [],
            "query_string": b"",
            "scheme": "http",
            "server": ("testserver", 80),
            "client": ("testclient", 50000),
        },
    )

    def admit_stale_request() -> None:
        dependency = get_current_user_with_media_lifecycle(
            request=request,
            current_user=user,
            db=db,
        )
        try:
            next(dependency)
            result.append("admitted")
        except BaseException as exc:
            result.append(exc)
        finally:
            dependency.close()

    with lock_account_lifecycle(
        data_dir=tmp_path,
        user_id=user.id,
        shared=False,
    ):
        contender = threading.Thread(target=admit_stale_request)
        contender.start()
        user_store.delete_user(user.id)

    contender.join(timeout=3)
    assert not contender.is_alive()
    assert len(result) == 1
    assert isinstance(result[0], HTTPException)
    assert result[0].status_code == 401

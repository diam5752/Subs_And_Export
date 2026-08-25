from __future__ import annotations

import base64
import binascii
import json
from collections.abc import Iterator
from contextlib import ExitStack, contextmanager
from typing import Annotated, Generator

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import OAuth2PasswordBearer

from ..core.auth import SessionStore, User, UserStore
from ..core.config import settings
from ..core.database import Database
from ..core.job_lifecycle import ACTIVE_JOB_STATUSES
from ..core.media_capacity import (
    MediaAdmissionLockTimeoutError,
    lock_media_admission,
)
from ..core.oauth_state import OAuthStateStore
from ..core.workspace_deletion import (
    AccountLifecycleLockTimeoutError,
    JobWorkspaceLockTimeoutError,
    lock_account_lifecycle,
    lock_job_workspace,
)
from ..services.billing import BillingService
from ..services.billing_consumer_records import BillingConsumerRecordStore
from ..services.history import HistoryStore
from ..services.jobs import JobStore
from ..services.points import PointsStore
from ..services.usage_ledger import UsageLedgerStore

# Simple OAuth2 scheme (Password flow) for Swagger UI
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="auth/token")

_PROCESS_STREAM_PATH = "/videos/process-stream"
_MAX_UPLOAD_METADATA_HEADER_CHARS = 12_000
_CANONICAL_VIDEO_CREDITS = frozenset({30, 60, 100})


def get_db(request: Request) -> Generator[Database, None, None]:
    """Dependency to get the app-scoped database instance."""
    db: Database = request.app.state.db
    yield db


def get_user_store(db: Database = Depends(get_db)) -> UserStore:
    return UserStore(db=db)


def get_session_store(db: Database = Depends(get_db)) -> SessionStore:
    return SessionStore(db=db)


def get_current_session_token(
    token: Annotated[str, Depends(oauth2_scheme)],
) -> str:
    """Return the presented bearer token for an already-authenticated request."""
    return token


def get_job_store(db: Database = Depends(get_db)) -> JobStore:
    return JobStore(db=db)


def get_history_store(db: Database = Depends(get_db)) -> HistoryStore:
    return HistoryStore(db=db)


def get_oauth_state_store(db: Database = Depends(get_db)) -> OAuthStateStore:
    return OAuthStateStore(db=db)


def get_points_store(db: Database = Depends(get_db)) -> PointsStore:
    return PointsStore(db=db)


def get_usage_ledger_store(
    db: Database = Depends(get_db),
    points_store: PointsStore = Depends(get_points_store),
) -> UsageLedgerStore:
    return UsageLedgerStore(db=db, points_store=points_store)


def get_billing_service(
    db: Database = Depends(get_db),
    points_store: PointsStore = Depends(get_points_store),
) -> BillingService:
    return BillingService(db=db, points_store=points_store)


def get_billing_consumer_record_store(
    db: Database = Depends(get_db),
) -> BillingConsumerRecordStore:
    return BillingConsumerRecordStore(db=db)


async def get_current_user(
    token: Annotated[str, Depends(oauth2_scheme)],
    session_store: SessionStore = Depends(get_session_store),
) -> User:
    """Validate session token and return current user."""
    user = session_store.authenticate(token)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Could not validate credentials",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return user


def _is_media_creation_request(request: Request) -> bool:
    path = request.url.path.rstrip("/")
    return path == _PROCESS_STREAM_PATH or path.endswith("/reprocess")


def _process_stream_authorization(request: Request) -> tuple[int, bool]:
    encoded = request.headers.get("x-gsubs-upload-metadata")
    if not encoded or len(encoded) > _MAX_UPLOAD_METADATA_HEADER_CHARS:
        raise HTTPException(status_code=400, detail="Invalid upload metadata")
    try:
        raw = base64.b64decode(encoded, validate=True)
        payload = json.loads(raw.decode("utf-8"))
        if not isinstance(payload, dict):
            raise ValueError("metadata must be an object")
        authorized_credits = payload.get("authorized_credits")
        if (
            isinstance(authorized_credits, bool)
            or not isinstance(authorized_credits, int)
            or authorized_credits not in _CANONICAL_VIDEO_CREDITS
        ):
            raise ValueError("invalid authorized credits")
        provider = payload.get(
            "transcribe_provider",
            settings.transcribe_tier_provider[settings.default_transcribe_tier],
        )
        if not isinstance(provider, str) or not provider.strip():
            raise ValueError("invalid provider")
        use_llm = payload.get("use_llm", settings.use_llm_by_default)
        if not isinstance(use_llm, bool):
            raise ValueError("invalid use_llm")
    except (
        binascii.Error,
        UnicodeDecodeError,
        json.JSONDecodeError,
        ValueError,
    ) as exc:
        raise HTTPException(status_code=400, detail="Invalid upload metadata") from exc

    normalized_provider = provider.strip().lower()
    require_paid = (
        not settings.mock_external_services
        and (
            not settings.is_dev
            or normalized_provider not in {"local", "mock"}
            or use_llm
        )
    )
    return authorized_credits, require_paid


def _preflight_process_stream_balance(
    *,
    request: Request,
    user_id: str,
    db: Database,
) -> None:
    authorized_credits, require_paid = _process_stream_authorization(request)
    PointsStore(db=db).assert_can_spend(
        user_id,
        authorized_credits,
        require_paid=require_paid,
    )


def _production_media_capacity_enforced() -> bool:
    return not settings.is_dev


def _assert_global_media_capacity(db: Database) -> None:
    active_jobs = JobStore(db=db).list_jobs_with_statuses(ACTIVE_JOB_STATUSES)
    if len(active_jobs) >= settings.max_active_media_jobs:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=(
                "Media processing is currently at capacity. "
                "Please retry after the active job finishes."
            ),
        )


@contextmanager
def media_job_admission(db: Database) -> Iterator[None]:
    """Atomically check global capacity while the caller creates one job."""
    try:
        with lock_media_admission(data_dir=settings.data_dir):
            if _production_media_capacity_enforced():
                _assert_global_media_capacity(db)
            yield
    except MediaAdmissionLockTimeoutError as exc:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=str(exc),
        ) from exc


def get_current_user_with_media_lifecycle(
    request: Request,
    current_user: User = Depends(get_current_user),
    db: Database = Depends(get_db),
) -> Generator[User, None, None]:
    """Hold the per-account lifecycle barrier for media requests.

    Authentication can complete immediately before a concurrent account
    erasure. Reloading the user only after acquiring the account barrier
    prevents that stale request from creating media after erasure succeeds.
    Global admission is deliberately scoped inside each creation endpoint so
    it ends before upload streaming and background processing begin.
    """
    media_creation = _is_media_creation_request(request)
    try:
        with ExitStack() as stack:
            stack.enter_context(
                lock_account_lifecycle(
                    data_dir=settings.data_dir,
                    user_id=current_user.id,
                    shared=not media_creation,
                ),
            )
            if UserStore(db=db).get_user_by_id(current_user.id) is None:
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="Could not validate credentials",
                    headers={"WWW-Authenticate": "Bearer"},
                )

            if media_creation:
                if (
                    request.url.path.rstrip("/") == _PROCESS_STREAM_PATH
                    and not settings.mock_external_services
                ):
                    _preflight_process_stream_balance(
                        request=request,
                        user_id=current_user.id,
                        db=db,
                    )
            yield current_user
    except AccountLifecycleLockTimeoutError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(exc),
        ) from exc


def get_current_user_with_locked_media_job(
    job_id: str,
    current_user: User = Depends(get_current_user_with_media_lifecycle),
) -> Generator[User, None, None]:
    """Hold account-then-job barriers for transcript-derived work.

    The nested dependency makes account erasure wait for the complete request,
    while the per-job lock makes individual project deletion wait as well.
    """
    try:
        with lock_job_workspace(
            data_dir=settings.data_dir,
            job_id=job_id,
        ):
            yield current_user
    except JobWorkspaceLockTimeoutError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(exc),
        ) from exc

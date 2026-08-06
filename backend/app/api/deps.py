from typing import Annotated, Generator

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import OAuth2PasswordBearer

from ..core.auth import SessionStore, User, UserStore
from ..core.config import settings
from ..core.database import Database
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
    session_store: SessionStore = Depends(get_session_store)
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


def get_current_user_with_media_lifecycle(
    current_user: User = Depends(get_current_user),
    db: Database = Depends(get_db),
) -> Generator[User, None, None]:
    """Hold the shared account barrier for one media-creation request.

    Authentication can complete immediately before a concurrent account
    erasure. Reloading the user only after acquiring the barrier prevents that
    stale request from creating an upload or reprocess workspace after erasure
    has already returned success.
    """
    try:
        with lock_account_lifecycle(
            data_dir=settings.data_dir,
            user_id=current_user.id,
            shared=True,
        ):
            if UserStore(db=db).get_user_by_id(current_user.id) is None:
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="Could not validate credentials",
                    headers={"WWW-Authenticate": "Bearer"},
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

from typing import Generator, Annotated
from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from jose import jwt, JWTError
from pydantic import ValidationError

from ..database import Database
from ..auth import UserStore, SessionStore, User
from ..jobs import JobStore
from ..history import HistoryStore
from .. import config

# Simple OAuth2 scheme (Password flow) for Swagger UI
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="auth/token")

def get_db() -> Generator[Database, None, None]:
    """Dependency to get a centralized database instance."""
    # In a real async app we might want session handling per request, 
    # but for sqlite wrapper we can just return the instance.
    # The wrapper handles connection pooling/context inside .connect()
    db = Database()
    yield db

def get_user_store(db: Database = Depends(get_db)) -> UserStore:
    return UserStore(db=db)

def get_session_store(db: Database = Depends(get_db)) -> SessionStore:
    return SessionStore(db=db)

def get_job_store(db: Database = Depends(get_db)) -> JobStore:
    return JobStore(db=db)

def get_history_store(db: Database = Depends(get_db)) -> HistoryStore:
    return HistoryStore(db=db)

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

from typing import Any, List
from fastapi import APIRouter, Depends

from ...auth import User
from ...history import HistoryStore, HistoryEvent
from ..deps import get_current_user, get_history_store

router = APIRouter()

@router.get("/", response_model=List[HistoryEvent])
def read_history(
    limit: int = 50,
    current_user: User = Depends(get_current_user),
    history_store: HistoryStore = Depends(get_history_store)
) -> Any:
    """Get recent history for the current user."""
    return history_store.recent_for_user(current_user, limit=limit)

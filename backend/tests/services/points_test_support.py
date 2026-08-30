"""Shared database setup for point-wallet tests."""

import uuid

from backend.app.core.database import Database
from backend.app.db.models import DbUser


def seed_user(
    db: Database,
    *,
    user_id: str | None = None,
    email: str | None = None,
    email_verified: bool = True,
) -> str:
    resolved_user_id = user_id or uuid.uuid4().hex
    resolved_email = email or f"{resolved_user_id}@example.com"
    with db.session() as session:
        session.add(
            DbUser(
                id=resolved_user_id,
                email=resolved_email,
                name="Test",
                provider="local",
                password_hash="x",
                google_sub=None,
                created_at="now",
                email_verified=email_verified,
            )
        )
    return resolved_user_id

import secrets

import pytest
from sqlalchemy.exc import IntegrityError

from backend.app.core.database import Database
from backend.app.db.models import DbUser


def test_google_subject_can_belong_to_only_one_user() -> None:
    suffix = secrets.token_hex(6)
    subject = f"google-subject-{suffix}"
    db = Database()

    with db.session() as session:
        session.add(
            DbUser(
                id=f"google-user-a-{suffix}",
                email=f"google-a-{suffix}@example.com",
                name="Google A",
                provider="google",
                password_hash=None,
                google_sub=subject,
                created_at="now",
                email_verified=True,
            )
        )

    with pytest.raises(IntegrityError):
        with db.session() as session:
            session.add(
                DbUser(
                    id=f"google-user-b-{suffix}",
                    email=f"google-b-{suffix}@example.com",
                    name="Google B",
                    provider="google",
                    password_hash=None,
                    google_sub=subject,
                    created_at="now",
                    email_verified=True,
                )
            )

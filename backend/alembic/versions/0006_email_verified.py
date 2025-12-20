"""Add email_verified field to users table.

Revision ID: 0006_email_verified
Revises: 0005_rate_limits
Create Date: 2024-12-20

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '0006_email_verified'
down_revision = '0005_rate_limits'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Add email_verified column with default False
    op.add_column(
        'users',
        sa.Column('email_verified', sa.Boolean(), nullable=False, server_default='false')
    )
    # Google OAuth users are automatically verified
    op.execute(
        "UPDATE users SET email_verified = true WHERE provider = 'google'"
    )


def downgrade() -> None:
    op.drop_column('users', 'email_verified')

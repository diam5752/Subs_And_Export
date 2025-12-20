"""Add rate_limits table for DB-backed rate limiting.

Revision ID: 0005_rate_limits
Revises: 0004_usage_ledger
Create Date: 2024-12-20

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '0005_rate_limits'
down_revision = '0004_usage_ledger'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'rate_limits',
        sa.Column('key', sa.String(255), primary_key=True),
        sa.Column('count', sa.Integer(), nullable=False, server_default='1'),
        sa.Column('window_start', sa.BigInteger(), nullable=False),
        sa.Column('expires_at', sa.BigInteger(), nullable=False),
    )
    # Index for cleanup queries
    op.create_index('ix_rate_limits_expires_at', 'rate_limits', ['expires_at'])


def downgrade() -> None:
    op.drop_index('ix_rate_limits_expires_at', table_name='rate_limits')
    op.drop_table('rate_limits')

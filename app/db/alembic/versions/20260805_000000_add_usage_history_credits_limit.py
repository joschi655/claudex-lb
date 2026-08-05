"""add usage history credits limit

Revision ID: 20260805_000000_add_usage_history_credits_limit
Revises: 20260804_010000_add_request_log_provider
Create Date: 2026-08-05
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20260805_000000_add_usage_history_credits_limit"
down_revision = "20260804_010000_add_request_log_provider"
branch_labels = None
depends_on = None

_TABLE_NAME = "usage_history"
_COLUMN_NAME = "credits_limit"


def _column_names(inspector: sa.Inspector) -> set[str]:
    return {column["name"] for column in inspector.get_columns(_TABLE_NAME)}


def upgrade() -> None:
    # ``credits_balance`` records what is left; a dollar-budget quota also needs
    # what the budget was, so a spend display can say "777 of 1000" rather than
    # inferring the total from a percentage. Nullable with no backfill: existing
    # rows never carried a limit, and NULL is the honest value for them.
    bind = op.get_bind()
    if _COLUMN_NAME not in _column_names(sa.inspect(bind)):
        op.add_column(_TABLE_NAME, sa.Column(_COLUMN_NAME, sa.Float(), nullable=True))


def downgrade() -> None:
    bind = op.get_bind()
    if _COLUMN_NAME in _column_names(sa.inspect(bind)):
        op.drop_column(_TABLE_NAME, _COLUMN_NAME)

"""add per-account pace and pre-reset window gates

Revision ID: 20260804_000000_add_account_pace_gates
Revises: 20260718_000000_add_account_provider
Create Date: 2026-08-04
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20260804_000000_add_account_pace_gates"
down_revision = "20260718_000000_add_account_provider"
branch_labels = None
depends_on = None

_TABLE_NAME = "accounts"
# NULL is the "gate off" value, so existing rows need no backfill: they keep
# exactly the selection behavior they had before this revision.
_COLUMNS: tuple[tuple[str, sa.types.TypeEngine], ...] = (
    ("pace_margin_primary_pct", sa.Float()),
    ("pace_margin_secondary_pct", sa.Float()),
    ("pre_reset_window_minutes", sa.Integer()),
)


def _column_names(inspector: sa.Inspector) -> set[str]:
    return {column["name"] for column in inspector.get_columns(_TABLE_NAME)}


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    columns = _column_names(inspector)
    for name, column_type in _COLUMNS:
        if name not in columns:
            op.add_column(_TABLE_NAME, sa.Column(name, column_type, nullable=True))


def downgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    columns = _column_names(inspector)
    for name, _ in _COLUMNS:
        if name in columns:
            with op.batch_alter_table(_TABLE_NAME) as batch_op:
                batch_op.drop_column(name)

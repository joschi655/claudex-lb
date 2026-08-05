"""add request log provider discriminator

Revision ID: 20260804_010000_add_request_log_provider
Revises: 20260804_000000_add_account_pace_gates
Create Date: 2026-08-04
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20260804_010000_add_request_log_provider"
down_revision = "20260804_000000_add_account_pace_gates"
branch_labels = None
depends_on = None

_TABLE_NAME = "request_logs"
_COLUMN_NAME = "provider"
_INDEX_NAME = "idx_logs_provider"


def _column_names(inspector: sa.Inspector) -> set[str]:
    return {column["name"] for column in inspector.get_columns(_TABLE_NAME)}


def _index_names(inspector: sa.Inspector) -> set[str]:
    return {index["name"] for index in inspector.get_indexes(_TABLE_NAME)}


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if _COLUMN_NAME not in _column_names(inspector):
        op.add_column(_TABLE_NAME, sa.Column(_COLUMN_NAME, sa.String(), nullable=True))

        # Every row that exists at this point predates Anthropic serving traffic,
        # so 'openai' is these rows' actual provider rather than a guess -- but
        # take it from the account where one still exists, so a database that has
        # already been carrying Anthropic rows is backfilled correctly too.
        op.execute(
            sa.text(
                f"UPDATE {_TABLE_NAME} SET {_COLUMN_NAME} = ("
                f"  SELECT accounts.provider FROM accounts"
                f"  WHERE accounts.id = {_TABLE_NAME}.account_id"
                f") WHERE {_TABLE_NAME}.account_id IS NOT NULL"
            )
        )
        op.execute(sa.text(f"UPDATE {_TABLE_NAME} SET {_COLUMN_NAME} = 'openai' WHERE {_COLUMN_NAME} IS NULL"))

    if _INDEX_NAME not in _index_names(sa.inspect(bind)):
        op.create_index(_INDEX_NAME, _TABLE_NAME, [_COLUMN_NAME])


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if _INDEX_NAME in _index_names(inspector):
        op.drop_index(_INDEX_NAME, table_name=_TABLE_NAME)
    if _COLUMN_NAME in _column_names(inspector):
        op.drop_column(_TABLE_NAME, _COLUMN_NAME)

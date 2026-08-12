"""let an operator declare whether an account is subscription or usage-based

Revision ID: 20260812_010000_add_account_quota_kind
Revises: 20260812_000000_add_request_log_cache_write_tokens
Create Date: 2026-08-12

Which quota surface an account presented was inferred from which usage rows
happened to exist. The inference stays, as the ``auto`` default, so every
existing row keeps the behaviour it already had -- there is nothing to backfill,
because ``auto`` *is* what they were doing.

The column exists for the cases the inference cannot reach: a seat polled before
its first budget read, a seat that moved to usage-based billing while its old
window rows lingered, or one that reports neither and so renders as a
subscription with nothing in it.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20260812_010000_add_account_quota_kind"
down_revision = "20260812_000000_add_request_log_cache_write_tokens"
branch_labels = None
depends_on = None

_TABLE_NAME = "accounts"
_COLUMN_NAME = "quota_kind"
_DEFAULT = "auto"


def _column_names(inspector: sa.Inspector) -> set[str]:
    return {column["name"] for column in inspector.get_columns(_TABLE_NAME)}


def upgrade() -> None:
    bind = op.get_bind()
    if _COLUMN_NAME in _column_names(sa.inspect(bind)):
        return
    op.add_column(
        _TABLE_NAME,
        sa.Column(
            _COLUMN_NAME,
            sa.String(),
            nullable=False,
            # text() rather than a bare string: the model declares the same
            # default as text("'auto'"), and the startup drift check compares
            # the rendered SQL, not the Python value.
            server_default=sa.text("'auto'"),
        ),
    )


def downgrade() -> None:
    bind = op.get_bind()
    if _COLUMN_NAME not in _column_names(sa.inspect(bind)):
        return
    with op.batch_alter_table(_TABLE_NAME) as batch_op:
        batch_op.drop_column(_COLUMN_NAME)

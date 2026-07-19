"""add account provider discriminator and anthropic token fields

Revision ID: 20260718_000000_add_account_provider
Revises: 20260716_000000_add_oauth_device_flow_slots
Create Date: 2026-07-18
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20260718_000000_add_account_provider"
down_revision = "20260716_000000_add_oauth_device_flow_slots"
branch_labels = None
depends_on = None

_TABLE_NAME = "accounts"


def _column_names(inspector: sa.Inspector) -> set[str]:
    return {column["name"] for column in inspector.get_columns(_TABLE_NAME)}


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    columns = _column_names(inspector)

    if "provider" not in columns:
        op.add_column(
            _TABLE_NAME,
            sa.Column(
                "provider",
                sa.String(),
                nullable=False,
                server_default=sa.text("'openai'"),
            ),
        )
    if "access_token_expires_at" not in columns:
        op.add_column(
            _TABLE_NAME,
            sa.Column("access_token_expires_at", sa.Integer(), nullable=True),
        )

    id_token_column = next(
        (column for column in inspector.get_columns(_TABLE_NAME) if column["name"] == "id_token_encrypted"),
        None,
    )
    if id_token_column is not None and not id_token_column["nullable"]:
        with op.batch_alter_table(_TABLE_NAME) as batch_op:
            batch_op.alter_column(
                "id_token_encrypted",
                existing_type=sa.LargeBinary(),
                nullable=True,
            )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    columns = _column_names(inspector)

    id_token_column = next(
        (column for column in inspector.get_columns(_TABLE_NAME) if column["name"] == "id_token_encrypted"),
        None,
    )
    if id_token_column is not None and id_token_column["nullable"]:
        op.execute(
            sa.text("UPDATE accounts SET id_token_encrypted = :empty WHERE id_token_encrypted IS NULL").bindparams(
                empty=b"",
            )
        )
        with op.batch_alter_table(_TABLE_NAME) as batch_op:
            batch_op.alter_column(
                "id_token_encrypted",
                existing_type=sa.LargeBinary(),
                nullable=False,
            )

    if "access_token_expires_at" in columns:
        with op.batch_alter_table(_TABLE_NAME) as batch_op:
            batch_op.drop_column("access_token_expires_at")
    if "provider" in columns:
        with op.batch_alter_table(_TABLE_NAME) as batch_op:
            batch_op.drop_column("provider")

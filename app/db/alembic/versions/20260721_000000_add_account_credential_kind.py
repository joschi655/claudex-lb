"""add account credential kind and request log provider

Revision ID: 20260721_000000_add_account_credential_kind
Revises: 20260718_000000_add_account_provider
Create Date: 2026-07-21
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20260721_000000_add_account_credential_kind"
down_revision = "20260718_000000_add_account_provider"
branch_labels = None
depends_on = None

_LEGACY_REASON = "unsupported_anthropic_oauth"


def _column_names(table_name: str) -> set[str]:
    inspector = sa.inspect(op.get_bind())
    return {column["name"] for column in inspector.get_columns(table_name)}


def upgrade() -> None:
    account_columns = _column_names("accounts")
    if "credential_kind" not in account_columns:
        op.add_column(
            "accounts",
            sa.Column(
                "credential_kind",
                sa.String(),
                nullable=False,
                server_default=sa.text("'openai_oauth'"),
            ),
        )

    op.execute(
        sa.text(
            "UPDATE accounts "
            "SET credential_kind = 'legacy_anthropic_oauth', "
            "status = 'deactivated', deactivation_reason = :reason, "
            "reset_at = NULL, blocked_at = NULL "
            "WHERE provider = 'anthropic'"
        ).bindparams(reason=_LEGACY_REASON)
    )

    request_log_columns = _column_names("request_logs")
    if "provider" not in request_log_columns:
        op.add_column(
            "request_logs",
            sa.Column(
                "provider",
                sa.String(),
                nullable=False,
                server_default=sa.text("'openai'"),
            ),
        )
        op.create_index("idx_logs_provider_requested_at", "request_logs", ["provider", "requested_at"])


def downgrade() -> None:
    bind = op.get_bind()
    account_columns = _column_names("accounts")
    if "provider" in account_columns:
        anthropic_count = bind.execute(sa.text("SELECT COUNT(*) FROM accounts WHERE provider <> 'openai'")).scalar_one()
        if anthropic_count:
            raise RuntimeError("Refusing to remove credential-kind safety while non-OpenAI accounts exist")

    request_log_columns = _column_names("request_logs")
    if "provider" in request_log_columns:
        anthropic_log_count = bind.execute(
            sa.text("SELECT COUNT(*) FROM request_logs WHERE provider <> 'openai'")
        ).scalar_one()
        if anthropic_log_count:
            raise RuntimeError("Refusing to remove request-log provider metadata while non-OpenAI logs exist")
        indexes = {index["name"] for index in sa.inspect(bind).get_indexes("request_logs")}
        if "idx_logs_provider_requested_at" in indexes:
            op.drop_index("idx_logs_provider_requested_at", table_name="request_logs")
        with op.batch_alter_table("request_logs") as batch_op:
            batch_op.drop_column("provider")

    if "credential_kind" in account_columns:
        with op.batch_alter_table("accounts") as batch_op:
            batch_op.drop_column("credential_kind")

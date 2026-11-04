"""add per-account usage ceilings and per-API-key account routing rules

Revision ID: 20261104_000000_add_usage_ceilings_and_key_routing_rules
Revises: 20260812_010000_add_account_quota_kind
Create Date: 2026-11-04
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20261104_000000_add_usage_ceilings_and_key_routing_rules"
down_revision = "20260812_010000_add_account_quota_kind"
branch_labels = None
depends_on = None

_ACCOUNTS = "accounts"
_RULES = "api_key_account_routing_rules"
# NULL is "no ceiling", so existing accounts keep their selection behavior and
# need no backfill. The rules table starts empty for the same reason: a key
# without rules inherits every account's own settings.
_CEILING_COLUMNS = ("usage_ceiling_primary_pct", "usage_ceiling_secondary_pct")


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    columns = {column["name"] for column in inspector.get_columns(_ACCOUNTS)}
    for name in _CEILING_COLUMNS:
        if name not in columns:
            op.add_column(_ACCOUNTS, sa.Column(name, sa.Float(), nullable=True))
    if not inspector.has_table(_RULES):
        op.create_table(
            _RULES,
            sa.Column(
                "api_key_id",
                sa.String(),
                sa.ForeignKey("api_keys.id", ondelete="CASCADE"),
                primary_key=True,
            ),
            sa.Column(
                "account_id",
                sa.String(),
                sa.ForeignKey("accounts.id", ondelete="CASCADE"),
                primary_key=True,
            ),
            sa.Column("routing_policy", sa.String(), nullable=True),
            sa.Column("override_gates", sa.Boolean(), nullable=False, server_default=sa.false()),
            sa.Column("usage_ceiling_primary_pct", sa.Float(), nullable=True),
            sa.Column("usage_ceiling_secondary_pct", sa.Float(), nullable=True),
            sa.Column("pace_margin_primary_pct", sa.Float(), nullable=True),
            sa.Column("pace_margin_secondary_pct", sa.Float(), nullable=True),
            sa.Column("pre_reset_window_minutes", sa.Integer(), nullable=True),
            sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        )


def downgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    if inspector.has_table(_RULES):
        op.drop_table(_RULES)
    columns = {column["name"] for column in inspector.get_columns(_ACCOUNTS)}
    for name in _CEILING_COLUMNS:
        if name in columns:
            with op.batch_alter_table(_ACCOUNTS) as batch_op:
                batch_op.drop_column(name)

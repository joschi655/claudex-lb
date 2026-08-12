"""move the operator pin out of routing_policy and onto its own column

Revision ID: 20260811_000000_add_account_pinned_flag
Revises: 20260805_000000_add_usage_history_credits_limit
Create Date: 2026-08-11

The pin was a fourth ``routing_policy`` value, which made it mutually exclusive
with the policy it should sit above: pinning an account overwrote whether it was
``preserve`` or ``burn_first``, and unpinning could only guess at what to restore.
A separate flag lets the pin be lifted and the account fall back to the policy it
already had.

Rows pinned under the old scheme are carried over as ``pinned = true``. Their
prior policy is not recoverable -- it was overwritten when they were pinned -- so
they land on ``normal``, which is the value the old pin path itself wrote when it
demoted a previous pin.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20260811_000000_add_account_pinned_flag"
down_revision = "20260805_000000_add_usage_history_credits_limit"
branch_labels = None
depends_on = None

_TABLE_NAME = "accounts"
_COLUMN_NAME = "pinned"
_LEGACY_POLICY = "pinned"
_FALLBACK_POLICY = "normal"


def _column_names(inspector: sa.Inspector) -> set[str]:
    return {column["name"] for column in inspector.get_columns(_TABLE_NAME)}


def upgrade() -> None:
    bind = op.get_bind()
    if _COLUMN_NAME not in _column_names(sa.inspect(bind)):
        op.add_column(
            _TABLE_NAME,
            sa.Column(
                _COLUMN_NAME,
                sa.Boolean(),
                nullable=False,
                server_default=sa.false(),
            ),
        )
    # Carry the old pins over before the legacy value stops being understood, so
    # a pool that was pinned at upgrade time stays pinned across the restart.
    bind.execute(
        sa.text(
            f"UPDATE {_TABLE_NAME} SET {_COLUMN_NAME} = :pinned, routing_policy = :fallback "
            "WHERE routing_policy = :legacy"
        ),
        {"pinned": True, "fallback": _FALLBACK_POLICY, "legacy": _LEGACY_POLICY},
    )


def downgrade() -> None:
    bind = op.get_bind()
    if _COLUMN_NAME not in _column_names(sa.inspect(bind)):
        return
    # Fold the flag back into the policy so the older code still finds its pins.
    bind.execute(
        sa.text(f"UPDATE {_TABLE_NAME} SET routing_policy = :legacy WHERE {_COLUMN_NAME} = :pinned"),
        {"legacy": _LEGACY_POLICY, "pinned": True},
    )
    with op.batch_alter_table(_TABLE_NAME) as batch_op:
        batch_op.drop_column(_COLUMN_NAME)

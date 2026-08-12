"""record prompt-cache writes separately and price the Claude rows already stored

Revision ID: 20260812_000000_add_request_log_cache_write_tokens
Revises: 20260811_000000_add_account_pinned_flag
Create Date: 2026-08-12

Anthropic bills three disjoint input counters at three rates: uncached input at
the base rate, cache reads at 0.1x, and cache writes at 1.25x. ``request_logs``
held a total and one subset, so a cache write was arithmetically
indistinguishable from uncached input and was necessarily charged at the base
rate. The new column keeps the third part.

The backfill prices the Anthropic rows written before Claude was in the price
table, which are stored with ``cost_usd IS NULL`` and therefore read as free in
every aggregate view. It cannot recover the cache-write split for them -- those
rows never stored it -- so their non-cache-read input is priced at the base
rate, which is the same approximation the old schema forced. Rows written from
here on are exact.

The rates are literals rather than an import of ``app.core.usage.pricing``: a
migration must compute the same thing forever, and a later price revision must
not silently rewrite what this one already did.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20260812_000000_add_request_log_cache_write_tokens"
down_revision = "20260811_000000_add_account_pinned_flag"
branch_labels = None
depends_on = None

_TABLE_NAME = "request_logs"
_COLUMN_NAME = "cache_write_input_tokens"

# (model prefix, base input, cache read, output) in USD per 1M tokens, read from
# the published model pricing table on 2026-08-12. Prefixes are matched with a
# trailing wildcard so snapshot-dated identifiers resolve too, and none of them
# is a prefix of another, so the order they are applied in does not matter.
_BACKFILL_RATES: tuple[tuple[str, float, float, float], ...] = (
    ("claude-fable-5", 10.0, 1.0, 50.0),
    ("claude-opus-5", 5.0, 0.5, 25.0),
    ("claude-opus-4-8", 5.0, 0.5, 25.0),
    ("claude-opus-4-7", 5.0, 0.5, 25.0),
    ("claude-opus-4-6", 5.0, 0.5, 25.0),
    ("claude-opus-4-5", 5.0, 0.5, 25.0),
    ("claude-sonnet-5", 2.0, 0.2, 10.0),
    ("claude-sonnet-4-6", 3.0, 0.3, 15.0),
    ("claude-sonnet-4-5", 3.0, 0.3, 15.0),
    ("claude-haiku-4-5", 1.0, 0.1, 5.0),
)

# Clamps the cache reads into the input total exactly as the application's
# read-time cost path does. The two must agree: the request-log mapper compares
# the stored cost against a fresh recomputation and drops the per-component
# breakdown when they differ, so a backfill that rounded differently would leave
# every historical row showing a total with no parts. CASE rather than
# GREATEST/MAX, which are spelled differently on PostgreSQL and SQLite.
_CACHED = (
    "(CASE WHEN COALESCE(cached_input_tokens, 0) < input_tokens"
    " THEN COALESCE(cached_input_tokens, 0) ELSE input_tokens END)"
)

_BACKFILL_SQL = sa.text(
    f"""
    UPDATE {_TABLE_NAME}
       SET cost_usd = (input_tokens - {_CACHED}) / 1000000.0 * :input_rate
                    + {_CACHED} / 1000000.0 * :cache_read_rate
                    + output_tokens / 1000000.0 * :output_rate
     WHERE cost_usd IS NULL
       AND input_tokens IS NOT NULL
       AND output_tokens IS NOT NULL
       AND model LIKE :pattern
    """
)


def _column_names(inspector: sa.Inspector) -> set[str]:
    return {column["name"] for column in inspector.get_columns(_TABLE_NAME)}


def upgrade() -> None:
    bind = op.get_bind()
    if _COLUMN_NAME not in _column_names(sa.inspect(bind)):
        op.add_column(_TABLE_NAME, sa.Column(_COLUMN_NAME, sa.Integer(), nullable=True))
    # Re-runnable by construction: the guard is `cost_usd IS NULL`, so a second
    # pass finds nothing left to price rather than compounding what it did.
    for pattern, input_rate, cache_read_rate, output_rate in _BACKFILL_RATES:
        bind.execute(
            _BACKFILL_SQL,
            {
                "pattern": f"{pattern}%",
                "input_rate": input_rate,
                "cache_read_rate": cache_read_rate,
                "output_rate": output_rate,
            },
        )


def downgrade() -> None:
    bind = op.get_bind()
    if _COLUMN_NAME not in _column_names(sa.inspect(bind)):
        return
    # The backfilled costs are deliberately left in place: nothing distinguishes
    # them from a cost the running code computed, and dropping every Anthropic
    # cost would discard correct rows to undo an approximation.
    with op.batch_alter_table(_TABLE_NAME) as batch_op:
        batch_op.drop_column(_COLUMN_NAME)

"""The cache-write counter, and the cost backfill that rides with it.

Contract: openspec/changes/price-claude-requests/specs/api-keys/spec.md.

The backfill has to agree with what the running application computes for the
same row, because the request-log mapper compares the two and drops the
per-component breakdown when they disagree. A test that only checked the
backfill against hand arithmetic would miss that, so the last test here checks
it against the application's own cost path.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest
import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations

from app.core.usage.logs import calculated_cost_from_log

REVISION = "20260812_000000_add_request_log_cache_write_tokens"
_REVISION_PATH = Path(__file__).resolve().parents[2] / "app/db/alembic/versions" / f"{REVISION}.py"

_COLUMN = "cache_write_input_tokens"


def _load_revision():
    """Import the revision by path: its module name starts with a digit."""
    spec = importlib.util.spec_from_file_location(f"revision_{REVISION}", _REVISION_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


migration = _load_revision()


class _Row:
    """The subset of ``RequestLogLike`` the cost path reads."""

    service_tier = None
    reasoning_tokens = None
    cost_usd = None
    cache_write_input_tokens = None

    def __init__(self, model, input_tokens, cached_input_tokens, output_tokens):
        self.model = model
        self.input_tokens = input_tokens
        self.cached_input_tokens = cached_input_tokens
        self.output_tokens = output_tokens


def _legacy_request_logs_table(connection: sa.Connection) -> None:
    """Only the columns this revision reads or writes, as they stood before it."""
    connection.execute(
        sa.text(
            "CREATE TABLE request_logs ("
            "  request_id TEXT PRIMARY KEY,"
            "  model TEXT,"
            "  input_tokens INTEGER,"
            "  output_tokens INTEGER,"
            "  cached_input_tokens INTEGER,"
            "  cost_usd REAL"
            ")"
        )
    )


def _seed(connection: sa.Connection, rows) -> None:
    for request_id, model, input_tokens, cached, output_tokens, cost in rows:
        connection.execute(
            sa.text(
                "INSERT INTO request_logs"
                " (request_id, model, input_tokens, output_tokens, cached_input_tokens, cost_usd)"
                " VALUES (:r, :m, :i, :o, :c, :u)"
            ),
            {"r": request_id, "m": model, "i": input_tokens, "o": output_tokens, "c": cached, "u": cost},
        )


def _costs(connection: sa.Connection) -> dict[str, float | None]:
    result = connection.execute(sa.text("SELECT request_id, cost_usd FROM request_logs"))
    return {row[0]: row[1] for row in result}


def _run(connection: sa.Connection, direction: str) -> None:
    context = MigrationContext.configure(connection)
    with Operations.context(context):
        getattr(migration, direction)()


def test_the_column_is_added_and_starts_null(tmp_path):
    engine = sa.create_engine(f"sqlite:///{tmp_path / 'cw.db'}")
    with engine.begin() as connection:
        _legacy_request_logs_table(connection)
        _seed(connection, [("a", "claude-opus-5", 100, 90, 10, None)])
        _run(connection, "upgrade")

        stored = connection.execute(sa.text(f"SELECT {_COLUMN} FROM request_logs")).scalar_one()

    # Null rather than zero: a row from before the counter existed is not a row
    # whose request wrote nothing to cache, and only one of them is a measurement.
    assert stored is None
    assert _COLUMN in {column["name"] for column in sa.inspect(engine).get_columns("request_logs")}


def test_unpriced_claude_history_is_backfilled(tmp_path):
    engine = sa.create_engine(f"sqlite:///{tmp_path / 'cw-backfill.db'}")
    with engine.begin() as connection:
        _legacy_request_logs_table(connection)
        _seed(
            connection,
            [
                ("opus", "claude-opus-5", 1000, 900, 100, None),
                ("haiku", "claude-haiku-4-5-20251001", 1000, 0, 100, None),
                ("sonnet", "claude-sonnet-5", 1000, 900, 100, None),
            ],
        )
        _run(connection, "upgrade")

        costs = _costs(connection)

    # 100 uncached at $5/M, 900 cache reads at $0.50/M, 100 output at $25/M.
    assert costs["opus"] == pytest.approx(100 / 1e6 * 5.0 + 900 / 1e6 * 0.5 + 100 / 1e6 * 25.0)
    # A snapshot-dated identifier is priced by its family, not skipped.
    assert costs["haiku"] == pytest.approx(1000 / 1e6 * 1.0 + 100 / 1e6 * 5.0)
    # Sonnet 5 at the standard $2/$10, not the cancelled $3/$15.
    assert costs["sonnet"] == pytest.approx(100 / 1e6 * 2.0 + 900 / 1e6 * 0.2 + 100 / 1e6 * 10.0)


def test_the_backfill_leaves_priced_and_unpriceable_rows_alone(tmp_path):
    engine = sa.create_engine(f"sqlite:///{tmp_path / 'cw-skip.db'}")
    with engine.begin() as connection:
        _legacy_request_logs_table(connection)
        _seed(
            connection,
            [
                # Already priced: an existing cost is never recomputed.
                ("priced", "claude-opus-5", 1000, 900, 100, 0.25),
                # An error row has no tokens to price.
                ("errored", "claude-opus-5", None, None, None, None),
                ("no-output", "claude-opus-5", 1000, 900, None, None),
                # A model outside the table stays unpriced.
                ("foreign", "some-other-model", 1000, 900, 100, None),
            ],
        )
        _run(connection, "upgrade")

        costs = _costs(connection)

    assert costs["priced"] == 0.25
    assert costs["errored"] is None
    assert costs["no-output"] is None
    assert costs["foreign"] is None


def test_the_backfill_is_safe_to_run_twice(tmp_path):
    engine = sa.create_engine(f"sqlite:///{tmp_path / 'cw-twice.db'}")
    with engine.begin() as connection:
        _legacy_request_logs_table(connection)
        _seed(connection, [("opus", "claude-opus-5", 1000, 900, 100, None)])
        _run(connection, "upgrade")
        once = _costs(connection)["opus"]
        _run(connection, "upgrade")

        assert _costs(connection)["opus"] == once


def test_the_downgrade_drops_the_column_and_keeps_the_costs(tmp_path):
    engine = sa.create_engine(f"sqlite:///{tmp_path / 'cw-down.db'}")
    with engine.begin() as connection:
        _legacy_request_logs_table(connection)
        _seed(connection, [("opus", "claude-opus-5", 1000, 900, 100, None)])
        _run(connection, "upgrade")
        priced = _costs(connection)["opus"]
        _run(connection, "downgrade")

        # Nothing distinguishes a backfilled cost from one the running code
        # computed, so undoing the approximation would discard correct rows too.
        assert _costs(connection)["opus"] == priced

    assert _COLUMN not in {column["name"] for column in sa.inspect(engine).get_columns("request_logs")}


@pytest.mark.parametrize(
    ("model", "input_tokens", "cached", "output_tokens"),
    [
        ("claude-opus-5", 1000, 900, 100),
        ("claude-sonnet-5", 250_000, 240_000, 3_000),
        ("claude-haiku-4-5-20251001", 912, 0, 33),
        # Cached above the total: both paths must clamp it the same way, or the
        # breakdown silently disappears for the row.
        ("claude-opus-5", 100, 500, 10),
    ],
)
def test_the_backfill_agrees_with_the_application_cost_path(tmp_path, model, input_tokens, cached, output_tokens):
    """Disagreement here is invisible in the API: the mapper keeps the stored
    total and blanks every component, so the row shows a price made of nothing."""
    engine = sa.create_engine(f"sqlite:///{tmp_path / 'cw-agree.db'}")
    with engine.begin() as connection:
        _legacy_request_logs_table(connection)
        _seed(connection, [("row", model, input_tokens, cached, output_tokens, None)])
        _run(connection, "upgrade")

        backfilled = _costs(connection)["row"]

    computed = calculated_cost_from_log(_Row(model, input_tokens, cached, output_tokens))

    assert computed is not None
    assert backfilled == pytest.approx(computed, abs=1e-9)

"""The quota-kind column's arrival.

Contract: openspec/changes/declare-account-quota-kind/specs/account-quota-presentation/spec.md.

There is nothing to backfill: ``auto`` is what every existing row was already
doing. The tests hold that it lands there and that nothing else moves.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations

REVISION = "20260812_010000_add_account_quota_kind"
_REVISION_PATH = Path(__file__).resolve().parents[2] / "app/db/alembic/versions" / f"{REVISION}.py"

_COLUMN = "quota_kind"


def _load_revision():
    """Import the revision by path: its module name starts with a digit."""
    spec = importlib.util.spec_from_file_location(f"revision_{REVISION}", _REVISION_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


migration = _load_revision()


def _legacy_accounts_table(connection: sa.Connection) -> None:
    connection.execute(
        sa.text(
            "CREATE TABLE accounts ("
            "  id TEXT PRIMARY KEY,"
            "  provider TEXT NOT NULL DEFAULT 'openai',"
            "  routing_policy TEXT NOT NULL DEFAULT 'normal'"
            ")"
        )
    )


def _seed(connection: sa.Connection, rows: list[tuple[str, str]]) -> None:
    for account_id, policy in rows:
        connection.execute(
            sa.text("INSERT INTO accounts (id, routing_policy) VALUES (:i, :r)"),
            {"i": account_id, "r": policy},
        )


def _run(connection: sa.Connection, direction: str) -> None:
    context = MigrationContext.configure(connection)
    with Operations.context(context):
        getattr(migration, direction)()


def test_existing_rows_land_on_auto(tmp_path):
    engine = sa.create_engine(f"sqlite:///{tmp_path / 'qk.db'}")
    with engine.begin() as connection:
        _legacy_accounts_table(connection)
        _seed(connection, [("a", "normal"), ("b", "preserve")])
        _run(connection, "upgrade")

        rows = {row[0]: row[1] for row in connection.execute(sa.text(f"SELECT id, {_COLUMN} FROM accounts"))}
        policies = {row[0]: row[1] for row in connection.execute(sa.text("SELECT id, routing_policy FROM accounts"))}

    # `auto` is not a migration choice so much as a description of what these
    # rows already did, which is why there is nothing to backfill.
    assert rows == {"a": "auto", "b": "auto"}
    assert policies == {"a": "normal", "b": "preserve"}


def test_the_upgrade_is_safe_to_run_twice(tmp_path):
    engine = sa.create_engine(f"sqlite:///{tmp_path / 'qk-twice.db'}")
    with engine.begin() as connection:
        _legacy_accounts_table(connection)
        _seed(connection, [("a", "normal")])
        _run(connection, "upgrade")
        connection.execute(sa.text(f"UPDATE accounts SET {_COLUMN} = 'usage_based'"))
        _run(connection, "upgrade")

        # A second pass must not reset a kind an operator has since set.
        assert connection.execute(sa.text(f"SELECT {_COLUMN} FROM accounts")).scalar_one() == "usage_based"


def test_the_downgrade_drops_the_column(tmp_path):
    engine = sa.create_engine(f"sqlite:///{tmp_path / 'qk-down.db'}")
    with engine.begin() as connection:
        _legacy_accounts_table(connection)
        _seed(connection, [("a", "preserve")])
        _run(connection, "upgrade")
        _run(connection, "downgrade")

        assert connection.execute(sa.text("SELECT routing_policy FROM accounts")).scalar_one() == "preserve"

    assert _COLUMN not in {column["name"] for column in sa.inspect(engine).get_columns("accounts")}

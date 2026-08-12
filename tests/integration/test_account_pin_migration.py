"""The pin's move out of ``routing_policy`` and onto its own column.

Contract: openspec/changes/show-the-next-serving-account/specs/account-routing/spec.md.

A pool that is pinned at upgrade time must stay pinned across the restart, and a
downgrade must hand the older code a pin it can still find.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations

REVISION = "20260811_000000_add_account_pinned_flag"
_REVISION_PATH = Path(__file__).resolve().parents[2] / "app/db/alembic/versions" / f"{REVISION}.py"


def _load_revision():
    """Import the revision by path: its module name starts with a digit."""
    spec = importlib.util.spec_from_file_location(f"revision_{REVISION}", _REVISION_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


migration = _load_revision()


def _legacy_accounts_table(connection: sa.Connection) -> None:
    """Only the columns this revision touches, as they stood before it."""
    connection.execute(
        sa.text(
            "CREATE TABLE accounts ("
            "  id TEXT PRIMARY KEY,"
            "  provider TEXT NOT NULL DEFAULT 'openai',"
            "  routing_policy TEXT NOT NULL DEFAULT 'normal'"
            ")"
        )
    )


def _seed(connection: sa.Connection, rows: list[tuple[str, str, str]]) -> None:
    for account_id, provider, policy in rows:
        connection.execute(
            sa.text("INSERT INTO accounts (id, provider, routing_policy) VALUES (:i, :p, :r)"),
            {"i": account_id, "p": provider, "r": policy},
        )


def _rows(connection: sa.Connection, columns: str) -> dict[str, tuple]:
    result = connection.execute(sa.text(f"SELECT id, {columns} FROM accounts ORDER BY id"))
    return {row[0]: tuple(row[1:]) for row in result}


def _run(connection: sa.Connection, direction: str) -> None:
    context = MigrationContext.configure(connection)
    with Operations.context(context):
        getattr(migration, direction)()


def test_an_existing_pin_survives_the_upgrade(tmp_path):
    engine = sa.create_engine(f"sqlite:///{tmp_path / 'pin.db'}")
    with engine.begin() as connection:
        _legacy_accounts_table(connection)
        _seed(
            connection,
            [
                ("held", "openai", "pinned"),
                ("kept", "openai", "preserve"),
                ("plain", "anthropic", "normal"),
            ],
        )
        _run(connection, "upgrade")

        rows = _rows(connection, "pinned, routing_policy")

    # The pin carries over, and the policy it overwrote is gone for good --
    # 'normal' is what the old pin path itself wrote when demoting a pin.
    assert rows["held"] == (1, "normal")
    # Every other account keeps exactly the policy it had, unpinned.
    assert rows["kept"] == (0, "preserve")
    assert rows["plain"] == (0, "normal")


def test_the_upgrade_is_safe_to_run_twice(tmp_path):
    engine = sa.create_engine(f"sqlite:///{tmp_path / 'pin-twice.db'}")
    with engine.begin() as connection:
        _legacy_accounts_table(connection)
        _seed(connection, [("held", "openai", "pinned")])
        _run(connection, "upgrade")
        _run(connection, "upgrade")

        assert _rows(connection, "pinned, routing_policy")["held"] == (1, "normal")


def test_the_downgrade_hands_the_pin_back_to_the_old_column(tmp_path):
    engine = sa.create_engine(f"sqlite:///{tmp_path / 'pin-down.db'}")
    with engine.begin() as connection:
        _legacy_accounts_table(connection)
        _seed(connection, [("held", "openai", "pinned"), ("kept", "openai", "preserve")])
        _run(connection, "upgrade")
        _run(connection, "downgrade")

        rows = _rows(connection, "routing_policy")

    assert rows["held"] == ("pinned",)
    assert rows["kept"] == ("preserve",)
    columns = {column["name"] for column in sa.inspect(engine).get_columns("accounts")}
    assert "pinned" not in columns

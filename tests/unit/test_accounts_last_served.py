"""Per-account last-served lookup: openspec/specs/account-routing/spec.md."""

from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import timedelta

import pytest
from sqlalchemy import insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.utils.time import utcnow
from app.db.models import Base, RequestLog
from app.modules.accounts.repository import AccountsRepository

pytestmark = pytest.mark.unit


@pytest.fixture
async def async_session() -> AsyncIterator[AsyncSession]:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    session = session_factory()
    try:
        yield session
    finally:
        await session.close()
        await engine.dispose()


_next_request_id = iter(f"req_{n}" for n in range(1000))


async def _log(session, account_id: str | None, *, minutes_ago: float) -> None:
    await session.execute(
        insert(RequestLog).values(
            request_id=next(_next_request_id),
            model="claude-opus-5",
            account_id=account_id,
            requested_at=utcnow() - timedelta(minutes=minutes_ago),
            status="ok",
        )
    )


@pytest.mark.asyncio
async def test_reports_the_newest_request_per_account(async_session) -> None:
    await _log(async_session, "a", minutes_ago=9)
    await _log(async_session, "a", minutes_ago=1)
    await _log(async_session, "b", minutes_ago=4)
    await async_session.commit()

    served = await AccountsRepository(async_session).last_served_at_by_account(since=utcnow() - timedelta(minutes=10))

    assert set(served) == {"a", "b"}
    assert served["a"] > served["b"]


@pytest.mark.asyncio
async def test_excludes_activity_older_than_the_window(async_session) -> None:
    await _log(async_session, "stale", minutes_ago=45)
    await async_session.commit()

    served = await AccountsRepository(async_session).last_served_at_by_account(since=utcnow() - timedelta(minutes=10))

    assert served == {}


@pytest.mark.asyncio
async def test_scopes_to_the_requested_accounts(async_session) -> None:
    await _log(async_session, "wanted", minutes_ago=1)
    await _log(async_session, "other", minutes_ago=1)
    await async_session.commit()

    repo = AccountsRepository(async_session)
    since = utcnow() - timedelta(minutes=10)

    assert set(await repo.last_served_at_by_account(since=since, account_ids=["wanted"])) == {"wanted"}
    # An empty scope is "no accounts", not "every account".
    assert await repo.last_served_at_by_account(since=since, account_ids=[]) == {}


@pytest.mark.asyncio
async def test_ignores_rows_with_no_account(async_session) -> None:
    # A request that failed before selection has no account to attribute.
    await _log(async_session, None, minutes_ago=1)
    await async_session.commit()

    served = await AccountsRepository(async_session).last_served_at_by_account(since=utcnow() - timedelta(minutes=10))

    assert served == {}

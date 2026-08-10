"""The warmup attempt repository's per-window view.

Contract: openspec/changes/retry-closed-window-warmups/specs/anthropic-provider/spec.md.
"""

from __future__ import annotations

from datetime import timedelta

import pytest

from app.core.crypto import TokenEncryptor
from app.core.utils.time import utcnow
from app.db.models import Account, AccountStatus
from app.db.session import SessionLocal
from app.modules.limit_warmup.repository import LimitWarmupRepository

pytestmark = pytest.mark.integration


def _account(account_id: str) -> Account:
    encryptor = TokenEncryptor()
    return Account(
        id=account_id,
        email=f"{account_id}@example.test",
        plan_type="max",
        access_token_encrypted=encryptor.encrypt("access"),
        refresh_token_encrypted=encryptor.encrypt("refresh"),
        id_token_encrypted=encryptor.encrypt("id"),
        last_refresh=utcnow(),
        status=AccountStatus.ACTIVE,
    )


async def _seed(*accounts: Account) -> None:
    async with SessionLocal() as session:
        for account in accounts:
            session.add(account)
        await session.commit()


@pytest.mark.asyncio
async def test_latest_is_reported_per_window_not_per_account(db_setup):
    """A per-account view collapses windows that close on unrelated schedules."""
    del db_setup
    await _seed(_account("acc-window-view"))
    now = utcnow()

    async with SessionLocal() as session:
        repo = LimitWarmupRepository(session)
        await repo.try_create_attempt(
            account_id="acc-window-view",
            window="primary",
            reset_at=1_000,
            model="claude-haiku-4-5-20251001",
            attempted_at=now - timedelta(hours=4),
        )
        await repo.try_create_attempt(
            account_id="acc-window-view",
            window="secondary",
            reset_at=2_000,
            model="claude-haiku-4-5-20251001",
            attempted_at=now - timedelta(minutes=5),
        )

        latest = await repo.latest_by_account_window(["acc-window-view"])

    windows = latest["acc-window-view"]
    assert set(windows) == {"primary", "secondary"}
    assert windows["primary"].reset_at == 1_000
    assert windows["secondary"].reset_at == 2_000
    # The per-account view sees only the newer one, which is exactly why the
    # cooldown could not be read off it.
    async with SessionLocal() as session:
        collapsed = await LimitWarmupRepository(session).latest_by_account(["acc-window-view"])
    assert collapsed["acc-window-view"].window == "secondary"


@pytest.mark.asyncio
async def test_the_newest_attempt_wins_within_a_window(db_setup):
    del db_setup
    await _seed(_account("acc-window-newest"))
    now = utcnow()

    async with SessionLocal() as session:
        repo = LimitWarmupRepository(session)
        for offset, reset_at in ((3, 3_000), (1, 5_000), (2, 4_000)):
            await repo.try_create_attempt(
                account_id="acc-window-newest",
                window="primary",
                reset_at=reset_at,
                model="claude-haiku-4-5-20251001",
                attempted_at=now - timedelta(hours=offset),
            )

        latest = await repo.latest_by_account_window(["acc-window-newest"])

    assert latest["acc-window-newest"]["primary"].reset_at == 5_000


@pytest.mark.asyncio
async def test_an_account_with_no_attempts_is_absent(db_setup):
    del db_setup
    await _seed(_account("acc-window-empty"))

    async with SessionLocal() as session:
        latest = await LimitWarmupRepository(session).latest_by_account_window(["acc-window-empty"])

    assert latest == {}

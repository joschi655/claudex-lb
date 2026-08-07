"""An account's extra-usage pool has to reach `/api/accounts` to be legible.

Extra usage is the pool that covers spend past a plan's own limits. It is the
only headroom a seat has left once its windows are spent, so a dashboard that
cannot see it cannot explain why an account is still serving -- or offer to turn
the pool on. A switched-off pool is reported too: "off" is the state an operator
acts on.
"""

from __future__ import annotations

import pytest

from app.core.anthropic.usage_ingest import EXTRA_CREDITS_WINDOW
from app.core.crypto import TokenEncryptor
from app.core.providers import PROVIDER_ANTHROPIC
from app.core.utils.time import utcnow
from app.db.models import Account, AccountStatus, UsageHistory
from app.db.session import SessionLocal

pytestmark = pytest.mark.integration


async def _add_account(account_id: str, *, plan_type: str) -> None:
    encryptor = TokenEncryptor()
    async with SessionLocal() as session:
        session.add(
            Account(
                id=account_id,
                chatgpt_account_id=None,
                email=f"{account_id}@example.com",
                plan_type=plan_type,
                provider=PROVIDER_ANTHROPIC,
                access_token_encrypted=encryptor.encrypt("sk-ant-oat-token"),
                refresh_token_encrypted=encryptor.encrypt("refresh"),
                id_token_encrypted=None,
                last_refresh=utcnow(),
                status=AccountStatus.ACTIVE,
            )
        )
        await session.commit()


async def _add_usage(account_id: str, **kwargs) -> None:
    async with SessionLocal() as session:
        session.add(UsageHistory(account_id=account_id, recorded_at=utcnow(), **kwargs))
        await session.commit()


async def _account_row(async_client, account_id: str) -> dict:
    response = await async_client.get("/api/accounts")
    assert response.status_code == 200
    rows = [row for row in response.json()["accounts"] if row["accountId"] == account_id]
    assert rows, f"{account_id} missing from /api/accounts"
    return rows[0]


@pytest.mark.asyncio
async def test_an_enabled_pool_reports_its_dollars(async_client):
    account_id = "anthropic-extra-credits-on"
    await _add_account(account_id, plan_type="claude_pro")
    await _add_usage(
        account_id,
        used_percent=8.015,
        window=EXTRA_CREDITS_WINDOW,
        credits_has=True,
        credits_unlimited=False,
        credits_balance=183.97,
        credits_limit=200.0,
    )

    row = await _account_row(async_client, account_id)

    credits = row["extraCredits"]
    assert credits is not None
    assert credits["enabled"] is True
    assert credits["usedPercent"] == pytest.approx(8.015)
    assert credits["limit"] == pytest.approx(200.0)
    assert credits["remaining"] == pytest.approx(183.97)
    # Spend is derived from the two stored figures so the three cannot disagree.
    assert credits["used"] == pytest.approx(16.03)
    assert credits["currency"] == "USD"


@pytest.mark.asyncio
async def test_a_disabled_pool_is_reported_rather_than_hidden(async_client):
    account_id = "anthropic-extra-credits-off"
    await _add_account(account_id, plan_type="claude_pro")
    await _add_usage(
        account_id,
        used_percent=0.0,
        window=EXTRA_CREDITS_WINDOW,
        credits_has=False,
        credits_unlimited=False,
        credits_balance=None,
        credits_limit=None,
    )

    row = await _account_row(async_client, account_id)

    credits = row["extraCredits"]
    assert credits is not None
    assert credits["enabled"] is False
    assert credits["limit"] is None
    assert credits["used"] is None


@pytest.mark.asyncio
async def test_an_account_that_reports_no_pool_carries_none(async_client):
    account_id = "anthropic-extra-credits-absent"
    await _add_account(account_id, plan_type="claude_pro")
    await _add_usage(account_id, used_percent=42.0, window="primary", window_minutes=300)

    row = await _account_row(async_client, account_id)

    assert row["extraCredits"] is None

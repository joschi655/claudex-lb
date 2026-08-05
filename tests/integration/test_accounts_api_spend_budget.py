"""A usage-based seat's dollar budget has to reach `/api/accounts` to be legible.

Such a seat reports no five-hour and no weekly window, so without the budget the
account row carries no quota information at all.
"""

from __future__ import annotations

import pytest

from app.core.anthropic.usage_ingest import BUDGET_WINDOW
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
async def test_budget_seat_exposes_its_spend_budget(async_client):
    account_id = "anthropic-budget-seat"
    await _add_account(account_id, plan_type="claude_enterprise")
    await _add_usage(
        account_id,
        used_percent=77.72440259999999,
        window=BUDGET_WINDOW,
        reset_at=1790822830,
        credits_has=True,
        credits_unlimited=False,
        credits_balance=222.75597400000004,
        credits_limit=1000.0,
    )

    row = await _account_row(async_client, account_id)

    budget = row["spendBudget"]
    assert budget is not None
    assert budget["usedPercent"] == pytest.approx(77.7244026)
    assert budget["limit"] == pytest.approx(1000.0)
    assert budget["remaining"] == pytest.approx(222.755974)
    # Spent is derived from the two stored figures so they cannot disagree.
    assert budget["used"] == pytest.approx(777.244026)
    assert budget["currency"] == "USD"
    assert budget["resetAt"] is not None


@pytest.mark.asyncio
async def test_window_seat_carries_no_spend_budget(async_client):
    account_id = "anthropic-window-seat"
    await _add_account(account_id, plan_type="claude_pro")
    await _add_usage(account_id, used_percent=42.0, window="primary", reset_at=1785936600, window_minutes=300)

    row = await _account_row(async_client, account_id)

    assert row["spendBudget"] is None


@pytest.mark.asyncio
async def test_budget_row_does_not_leak_into_the_five_hour_window(async_client):
    """A budget is not a rolling window and must not be read as one."""
    account_id = "anthropic-budget-only"
    await _add_account(account_id, plan_type="claude_enterprise")
    await _add_usage(
        account_id,
        used_percent=90.0,
        window=BUDGET_WINDOW,
        reset_at=1790822830,
        credits_has=True,
        credits_balance=100.0,
        credits_limit=1000.0,
    )

    row = await _account_row(async_client, account_id)

    assert row["usage"]["primaryRemainingPercent"] is None
    assert row["usage"]["secondaryRemainingPercent"] is None
    assert row["spendBudget"]["usedPercent"] == pytest.approx(90.0)

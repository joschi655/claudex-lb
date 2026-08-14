"""A usage-based seat's dollar pools reach the dashboard overview.

Contract: openspec/changes/headline-the-live-quota-pool/specs/account-quota-presentation/spec.md.

The overview loaded the three window kinds and nothing else, so a seat that
reports none of them — an enterprise seat billing against dollars — arrived with
every quota field null and no pool to fall back on. The same seat rendered its
budget on the accounts page and nothing at all on the dashboard, which is the
disagreement these tests exist to keep closed.
"""

from __future__ import annotations

import pytest

from app.core.anthropic.usage_ingest import BUDGET_WINDOW, EXTRA_CREDITS_WINDOW
from app.core.utils.time import utcnow
from app.db.session import SessionLocal
from app.modules.accounts.repository import AccountsRepository
from app.modules.usage.repository import UsageRepository
from tests.integration.test_dashboard_overview import _make_account

pytestmark = pytest.mark.integration


async def _seed_usage_based_seat(account_id: str) -> None:
    """The live enterprise seat's shape: plan allowance spent, top-up part-used."""
    async with SessionLocal() as session:
        accounts_repo = AccountsRepository(session)
        usage_repo = UsageRepository(session)

        await accounts_repo.upsert(
            _make_account(account_id, f"{account_id}@example.com", plan_type="claude_enterprise")
        )
        # Deliberately no primary/secondary/monthly rows: reporting none of them
        # is what makes this seat usage-based in the first place.
        await usage_repo.add_entry(
            account_id,
            100.0,
            window=BUDGET_WINDOW,
            recorded_at=utcnow(),
            credits_limit=1000.0,
            credits_balance=0.0,
        )
        await usage_repo.add_entry(
            account_id,
            42.43,
            window=EXTRA_CREDITS_WINDOW,
            recorded_at=utcnow(),
            credits_has=True,
            credits_limit=200.0,
            credits_balance=115.14,
        )


async def _overview_account(async_client, account_id: str) -> dict:
    response = await async_client.get("/api/dashboard/overview")
    assert response.status_code == 200, response.text
    return next(a for a in response.json()["accounts"] if a["accountId"] == account_id)


@pytest.mark.asyncio
async def test_overview_carries_the_spend_budget(async_client, db_setup):
    await _seed_usage_based_seat("acc_budget_overview")

    account = await _overview_account(async_client, "acc_budget_overview")

    assert account["spendBudget"] is not None
    assert account["spendBudget"]["usedPercent"] == pytest.approx(100.0)
    assert account["spendBudget"]["limit"] == pytest.approx(1000.0)
    assert account["spendBudget"]["remaining"] == pytest.approx(0.0)


@pytest.mark.asyncio
async def test_overview_carries_the_extra_usage_pool(async_client, db_setup):
    # The pool the seat can still spend from once the budget is gone. Without it
    # the overview can only report the spent budget, which reads as a dead seat.
    await _seed_usage_based_seat("acc_extra_overview")

    account = await _overview_account(async_client, "acc_extra_overview")

    assert account["extraCredits"] is not None
    assert account["extraCredits"]["enabled"] is True
    assert account["extraCredits"]["usedPercent"] == pytest.approx(42.43)
    assert account["extraCredits"]["limit"] == pytest.approx(200.0)
    assert account["extraCredits"]["remaining"] == pytest.approx(115.14)


@pytest.mark.asyncio
async def test_overview_and_accounts_agree_on_the_pools(async_client, db_setup):
    """The two endpoints described the same seat differently; they must not."""
    await _seed_usage_based_seat("acc_agree_overview")

    overview = await _overview_account(async_client, "acc_agree_overview")
    accounts = (await async_client.get("/api/accounts")).json()["accounts"]
    listed = next(a for a in accounts if a["accountId"] == "acc_agree_overview")

    assert overview["spendBudget"] == listed["spendBudget"]
    assert overview["extraCredits"] == listed["extraCredits"]


@pytest.mark.asyncio
async def test_a_usage_based_only_pool_reports_a_sync_time(async_client, db_setup):
    """A live poller must not read as stalled just because no seat has a window.

    `lastSyncAt` answered "is the poller alive" from the three window kinds
    alone. A pool of usage-based seats reports none of them, so it showed as
    never synced while the poller was writing dollar rows every tick.
    """
    await _seed_usage_based_seat("acc_sync_overview")

    response = await async_client.get("/api/dashboard/overview")
    assert response.status_code == 200, response.text

    assert response.json()["lastSyncAt"] is not None


@pytest.mark.asyncio
async def test_a_window_account_reports_no_pools(async_client, db_setup):
    """Loading two more windows must not invent pools for a subscription seat."""
    async with SessionLocal() as session:
        accounts_repo = AccountsRepository(session)
        usage_repo = UsageRepository(session)
        await accounts_repo.upsert(_make_account("acc_window_overview", "window@example.com"))
        await usage_repo.add_entry("acc_window_overview", 20.0, window="primary", recorded_at=utcnow())
        await usage_repo.add_entry("acc_window_overview", 40.0, window="secondary", recorded_at=utcnow())

    account = await _overview_account(async_client, "acc_window_overview")

    assert account["spendBudget"] is None
    assert account["extraCredits"] is None
    assert account["usage"]["primaryRemainingPercent"] == pytest.approx(80.0)

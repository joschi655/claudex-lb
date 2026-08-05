"""Persist an Anthropic usage snapshot into the shared usage-history windows.

Both the relay (from a served response) and limit warmup (from its ping's
response) observe the same ``anthropic-ratelimit-unified-*`` headers, so the
window durations and the write itself live here rather than in either caller.
The usage-API poller writes through the same functions, so a window row means the
same thing whichever of the three learned it.
"""

from __future__ import annotations

from app.core.anthropic.usage_api import AnthropicUsageApiSnapshot
from app.core.anthropic.usage_headers import AnthropicUsageSnapshot
from app.modules.usage.repository import UsageRepository

ANTHROPIC_PRIMARY_WINDOW_MINUTES = 5 * 60
ANTHROPIC_SECONDARY_WINDOW_MINUTES = 7 * 24 * 60

# A dollar budget is not a rolling window -- it runs to a billing date, and the
# span between resets varies. ``BUDGET_WINDOW`` marks the row as that kind of
# quota so consumers do not read it as a five-hour or weekly sample.
BUDGET_WINDOW = "budget"


async def persist_usage_snapshot(
    repo: UsageRepository,
    account_id: str,
    snapshot: AnthropicUsageSnapshot,
) -> None:
    if snapshot.primary_used_percent is not None:
        await repo.add_entry(
            account_id,
            used_percent=snapshot.primary_used_percent,
            window="primary",
            reset_at=snapshot.primary_reset_at,
            window_minutes=ANTHROPIC_PRIMARY_WINDOW_MINUTES,
        )
    if snapshot.secondary_used_percent is not None:
        await repo.add_entry(
            account_id,
            used_percent=snapshot.secondary_used_percent,
            window="secondary",
            reset_at=snapshot.secondary_reset_at,
            window_minutes=ANTHROPIC_SECONDARY_WINDOW_MINUTES,
        )


async def persist_usage_api_snapshot(
    repo: UsageRepository,
    account_id: str,
    snapshot: AnthropicUsageApiSnapshot,
) -> bool:
    """Write a polled snapshot. Returns whether any row was written.

    Each window is written independently: a seat reporting only a budget writes
    only a budget row, and a subscription seat writes only its two windows. A
    window the payload does not mention is left alone rather than zeroed --
    absent is not the same as empty.
    """
    written = False
    if snapshot.primary is not None:
        await repo.add_entry(
            account_id,
            used_percent=snapshot.primary.used_percent,
            window="primary",
            reset_at=snapshot.primary.reset_at,
            window_minutes=ANTHROPIC_PRIMARY_WINDOW_MINUTES,
        )
        written = True
    if snapshot.secondary is not None:
        await repo.add_entry(
            account_id,
            used_percent=snapshot.secondary.used_percent,
            window="secondary",
            reset_at=snapshot.secondary.reset_at,
            window_minutes=ANTHROPIC_SECONDARY_WINDOW_MINUTES,
        )
        written = True
    budget = snapshot.budget
    if budget is not None:
        # The dollar figures ride in the credit columns: a budget's remainder is
        # exactly what ``credits_balance`` already means, and ``credits_limit``
        # carries the total so the display need not infer it from the percentage.
        await repo.add_entry(
            account_id,
            used_percent=budget.used_percent,
            window=BUDGET_WINDOW,
            reset_at=budget.reset_at,
            credits_has=True,
            credits_unlimited=False,
            credits_balance=budget.remaining_dollars,
            credits_limit=budget.limit_dollars,
        )
        written = True
    return written

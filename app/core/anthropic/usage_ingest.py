"""Persist an Anthropic usage snapshot into the shared usage-history windows.

Both the relay (from a served response) and limit warmup (from its ping's
response) observe the same ``anthropic-ratelimit-unified-*`` headers, so the
window durations and the write itself live here rather than in either caller.
"""

from __future__ import annotations

from app.core.anthropic.usage_headers import AnthropicUsageSnapshot
from app.modules.usage.repository import UsageRepository

ANTHROPIC_PRIMARY_WINDOW_MINUTES = 5 * 60
ANTHROPIC_SECONDARY_WINDOW_MINUTES = 7 * 24 * 60


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

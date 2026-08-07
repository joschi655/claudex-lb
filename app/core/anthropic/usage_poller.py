"""Poll Anthropic accounts for their quota state instead of waiting for traffic.

Header ingestion only learns about an account the pool is actively using. An idle
account's last sample stands as its state indefinitely -- so a sample that was
wrong when it was written stays wrong, and the selector keeps acting on it. This
poller bounds that staleness to one refresh interval for every account, used or
not, and is the only path that can see a usage-based seat's dollar budget at all
(such a seat reports no window, so no response header ever describes it).

Failures are contained per account. The poll shares a scheduler tick with the
OpenAI usage refresh and with limit warmup, and must not be able to disturb
either.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable, Iterable
from contextlib import AbstractAsyncContextManager
from dataclasses import dataclass
from typing import TypeAlias

from app.core.anthropic.usage_api import (
    AnthropicUsageApiSnapshot,
    AnthropicUsageFetchError,
    fetch_anthropic_usage,
)
from app.core.anthropic.usage_ingest import persist_usage_api_snapshot
from app.core.crypto import TokenEncryptor
from app.core.providers import is_anthropic_provider
from app.db.models import Account, AccountStatus
from app.modules.usage.repository import UsageRepository

logger = logging.getLogger(__name__)

# The endpoint throttles hard, and Claude Code polls it against the same account
# from every live session, so the pool is sharing a budget with its own clients.
# A 429 therefore means "come back later", and later is generously defined.
THROTTLED_COOLDOWN_SECONDS = 15 * 60
# An auth failure will not fix itself on the next tick; the credential has to be
# repaired first, and the refresh path already reports on that.
UNAUTHORIZED_COOLDOWN_SECONDS = 60 * 60
# An unchanged snapshot is still written this often, so consumers that treat a
# stale ``recorded_at`` as "no longer reporting" keep seeing a live account. The
# same shape as the live-ingest throttle: changed writes are never deferred.
UNCHANGED_WRITE_INTERVAL_SECONDS = 10 * 60

_NOT_POLLABLE_STATUSES = frozenset({AccountStatus.DEACTIVATED, AccountStatus.REAUTH_REQUIRED})

_cooldowns: dict[str, float] = {}
_last_write: dict[str, tuple[tuple[object, ...], float]] = {}

# Each write gets its own short-lived session: the caller owns session scope, and
# one session must not be shared across the sequence of per-account writes.
UsageRepoContext: TypeAlias = AbstractAsyncContextManager[UsageRepository]


@dataclass(frozen=True, slots=True)
class AnthropicUsagePollOutcome:
    polled: int = 0
    written: int = 0
    throttled: int = 0
    failed: int = 0


def pollable_anthropic_accounts(accounts: Iterable[Account]) -> list[Account]:
    """Accounts worth asking about: Anthropic, credentialed, not in cooldown.

    A paused account is included on purpose. Paused means "kept out of the
    serving pool", not "stop tracking" -- its window keeps ageing and the
    operator switching back to it wants a true number, not the one from whenever
    it was last used.
    """
    return [
        account
        for account in accounts
        if is_anthropic_provider(account.provider or "")
        and account.status not in _NOT_POLLABLE_STATUSES
        and account.access_token_encrypted
        and not _in_cooldown(account.id)
    ]


async def poll_anthropic_usage(
    accounts: Iterable[Account],
    *,
    encryptor: TokenEncryptor,
    usage_repo_factory: Callable[[], UsageRepoContext],
) -> AnthropicUsagePollOutcome:
    """Refresh each account's stored quota state from Anthropic's usage API.

    Accounts are polled sequentially. The fan-out is at most one request per
    Anthropic account per refresh interval, and running them concurrently would
    make the throttling worse for no benefit at this scale.
    """
    polled = written = throttled = failed = 0
    for account in pollable_anthropic_accounts(accounts):
        try:
            credential = encryptor.decrypt(account.access_token_encrypted)
        except Exception:
            logger.warning("Anthropic usage poll could not read credential account_id=%s", account.id)
            failed += 1
            continue
        try:
            snapshot = await fetch_anthropic_usage(credential)
        except AnthropicUsageFetchError as exc:
            if exc.throttled:
                _set_cooldown(account.id, THROTTLED_COOLDOWN_SECONDS)
                throttled += 1
                # Not a warning: an account is expected to be throttled here
                # whenever one of its own sessions is polling the same endpoint.
                logger.debug("Anthropic usage poll throttled account_id=%s", account.id)
                continue
            if exc.unauthorized:
                _set_cooldown(account.id, UNAUTHORIZED_COOLDOWN_SECONDS)
            failed += 1
            logger.info(
                "Anthropic usage poll failed account_id=%s reason=%s",
                account.id,
                exc.reason,
            )
            continue
        except Exception:
            failed += 1
            logger.warning("Anthropic usage poll raised account_id=%s", account.id, exc_info=True)
            continue
        polled += 1
        if not snapshot.has_any or _should_skip_write(account.id, snapshot):
            continue
        try:
            async with usage_repo_factory() as usage_repo:
                if await persist_usage_api_snapshot(usage_repo, account.id, snapshot):
                    written += 1
                    _last_write[account.id] = (_fingerprint(snapshot), time.monotonic())
        except Exception:
            failed += 1
            logger.warning("Anthropic usage poll could not persist account_id=%s", account.id, exc_info=True)
    return AnthropicUsagePollOutcome(polled=polled, written=written, throttled=throttled, failed=failed)


def _fingerprint(snapshot: AnthropicUsageApiSnapshot) -> tuple[object, ...]:
    return (
        snapshot.primary.used_percent if snapshot.primary else None,
        snapshot.primary.reset_at if snapshot.primary else None,
        snapshot.secondary.used_percent if snapshot.secondary else None,
        snapshot.secondary.reset_at if snapshot.secondary else None,
        snapshot.budget.used_percent if snapshot.budget else None,
        snapshot.budget.remaining_dollars if snapshot.budget else None,
        snapshot.budget.reset_at if snapshot.budget else None,
        # Extra-credit spend moves independently of the windows: leaving it out
        # would hold a stale pool on screen for the whole unchanged-write
        # interval whenever the quota figures happen not to move.
        snapshot.extra_credits.enabled if snapshot.extra_credits else None,
        snapshot.extra_credits.used_dollars if snapshot.extra_credits else None,
        snapshot.extra_credits.limit_dollars if snapshot.extra_credits else None,
    )


def _should_skip_write(account_id: str, snapshot: AnthropicUsageApiSnapshot) -> bool:
    """Skip a write that would only restate the row already stored.

    A poll every refresh interval otherwise appends an identical row for an
    account nobody is using, which is most of them most of the time.
    """
    last = _last_write.get(account_id)
    if last is None:
        return False
    fingerprint, written_at = last
    if fingerprint != _fingerprint(snapshot):
        return False
    return time.monotonic() - written_at < UNCHANGED_WRITE_INTERVAL_SECONDS


def _in_cooldown(account_id: str) -> bool:
    expires_at = _cooldowns.get(account_id)
    if expires_at is None:
        return False
    if expires_at > time.monotonic():
        return True
    _cooldowns.pop(account_id, None)
    return False


def _set_cooldown(account_id: str, seconds: float) -> None:
    if seconds <= 0:
        return
    _cooldowns[account_id] = time.monotonic() + seconds


def clear_anthropic_usage_poll_cooldowns() -> None:
    _cooldowns.clear()
    _last_write.clear()

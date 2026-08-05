"""The poller's contract: contain failures, back off on 429, keep going."""

from __future__ import annotations

import contextlib
from dataclasses import dataclass, field
from typing import Any

import pytest

from app.core.anthropic import usage_poller
from app.core.anthropic.usage_api import (
    AnthropicSpendBudget,
    AnthropicUsageApiSnapshot,
    AnthropicUsageFetchError,
    AnthropicUsageWindow,
)
from app.core.anthropic.usage_ingest import BUDGET_WINDOW
from app.core.anthropic.usage_poller import (
    clear_anthropic_usage_poll_cooldowns,
    poll_anthropic_usage,
    pollable_anthropic_accounts,
)
from app.core.providers import PROVIDER_ANTHROPIC, PROVIDER_OPENAI
from app.core.utils.time import utcnow
from app.db.models import Account, AccountStatus

pytestmark = pytest.mark.unit


@pytest.fixture(autouse=True)
def _clear_cooldowns():
    clear_anthropic_usage_poll_cooldowns()
    yield
    clear_anthropic_usage_poll_cooldowns()


def _account(
    account_id: str = "anthropic-1",
    *,
    provider: str = PROVIDER_ANTHROPIC,
    status: AccountStatus = AccountStatus.ACTIVE,
    token: bytes | None = b"access",
) -> Account:
    return Account(
        id=account_id,
        chatgpt_account_id=None,
        email=f"{account_id}@example.com",
        plan_type="claude_pro",
        provider=provider,
        access_token_encrypted=token,
        refresh_token_encrypted=b"refresh",
        id_token_encrypted=None,
        last_refresh=utcnow(),
        status=status,
        deactivation_reason=None,
    )


class FakeEncryptor:
    def __init__(self, *, raises_for: set[str] | None = None) -> None:
        self._raises_for = raises_for or set()

    def decrypt(self, blob: bytes) -> str:
        token = blob.decode()
        if token in self._raises_for:
            raise ValueError("cannot decrypt")
        return f"sk-ant-oat-{token}"


@dataclass
class RecordedWrite:
    account_id: str
    window: str | None
    used_percent: float
    reset_at: int | None
    credits_balance: float | None = None
    credits_limit: float | None = None


@dataclass
class FakeUsageRepo:
    writes: list[RecordedWrite] = field(default_factory=list)

    async def add_entry(self, account_id: str, used_percent: float, **kwargs: Any):
        self.writes.append(
            RecordedWrite(
                account_id=account_id,
                window=kwargs.get("window"),
                used_percent=used_percent,
                reset_at=kwargs.get("reset_at"),
                credits_balance=kwargs.get("credits_balance"),
                credits_limit=kwargs.get("credits_limit"),
            )
        )


def _repo_factory(repo: FakeUsageRepo):
    @contextlib.asynccontextmanager
    async def factory():
        yield repo

    return factory


def _windows_snapshot(primary: float = 100.0) -> AnthropicUsageApiSnapshot:
    return AnthropicUsageApiSnapshot(
        primary=AnthropicUsageWindow(used_percent=primary, reset_at=1785936600),
        secondary=AnthropicUsageWindow(used_percent=27.0, reset_at=1786168800),
    )


def _budget_snapshot() -> AnthropicUsageApiSnapshot:
    return AnthropicUsageApiSnapshot(
        budget=AnthropicSpendBudget(
            used_percent=77.72,
            used_dollars=777.24,
            limit_dollars=1000.0,
            remaining_dollars=222.76,
            currency="USD",
            reset_at=1790822830,
        )
    )


def test_openai_accounts_are_never_polled():
    accounts = [_account("openai-1", provider=PROVIDER_OPENAI), _account("anthropic-1")]

    assert [a.id for a in pollable_anthropic_accounts(accounts)] == ["anthropic-1"]


def test_paused_accounts_are_polled_but_dead_ones_are_not():
    """Paused means "out of the serving pool", not "stop tracking its window"."""
    accounts = [
        _account("paused", status=AccountStatus.PAUSED),
        _account("reauth", status=AccountStatus.REAUTH_REQUIRED),
        _account("dead", status=AccountStatus.DEACTIVATED),
        _account("limited", status=AccountStatus.RATE_LIMITED),
    ]

    assert sorted(a.id for a in pollable_anthropic_accounts(accounts)) == ["limited", "paused"]


def test_accounts_without_a_stored_token_are_skipped():
    assert pollable_anthropic_accounts([_account("no-token", token=None)]) == []


@pytest.mark.asyncio
async def test_polled_windows_are_written(monkeypatch):
    repo = FakeUsageRepo()
    monkeypatch.setattr(usage_poller, "fetch_anthropic_usage", _fetch_returning(_windows_snapshot()))

    outcome = await poll_anthropic_usage(
        [_account()],
        encryptor=FakeEncryptor(),
        usage_repo_factory=_repo_factory(repo),
    )

    assert outcome.polled == 1
    assert outcome.written == 1
    assert [(w.window, w.used_percent) for w in repo.writes] == [("primary", 100.0), ("secondary", 27.0)]


@pytest.mark.asyncio
async def test_a_stale_row_is_replaced_by_the_polled_value(monkeypatch):
    """The whole point: an idle account converges on the truth.

    Mirrors the production case where a stored 1.06% sample outlived a window the
    account had actually spent.
    """
    repo = FakeUsageRepo()
    monkeypatch.setattr(usage_poller, "fetch_anthropic_usage", _fetch_returning(_windows_snapshot(primary=100.0)))

    await poll_anthropic_usage(
        [_account()],
        encryptor=FakeEncryptor(),
        usage_repo_factory=_repo_factory(repo),
    )

    primary = [w for w in repo.writes if w.window == "primary"]
    assert [w.used_percent for w in primary] == [100.0]


@pytest.mark.asyncio
async def test_a_budget_seat_writes_a_budget_row_with_its_dollars(monkeypatch):
    repo = FakeUsageRepo()
    monkeypatch.setattr(usage_poller, "fetch_anthropic_usage", _fetch_returning(_budget_snapshot()))

    outcome = await poll_anthropic_usage(
        [_account()],
        encryptor=FakeEncryptor(),
        usage_repo_factory=_repo_factory(repo),
    )

    assert outcome.written == 1
    assert len(repo.writes) == 1
    write = repo.writes[0]
    assert write.window == BUDGET_WINDOW
    assert write.used_percent == 77.72
    assert write.credits_limit == 1000.0
    assert write.credits_balance == 222.76
    assert write.reset_at == 1790822830


@pytest.mark.asyncio
async def test_throttling_backs_the_account_off_without_touching_it(monkeypatch):
    repo = FakeUsageRepo()
    account = _account()
    monkeypatch.setattr(
        usage_poller,
        "fetch_anthropic_usage",
        _fetch_raising(AnthropicUsageFetchError("http_429", status_code=429)),
    )

    outcome = await poll_anthropic_usage(
        [account],
        encryptor=FakeEncryptor(),
        usage_repo_factory=_repo_factory(repo),
    )

    assert outcome.throttled == 1
    assert outcome.failed == 0
    assert account.status == AccountStatus.ACTIVE
    assert repo.writes == []
    # The cooldown holds, so a second tick does not spend another request.
    assert pollable_anthropic_accounts([account]) == []


@pytest.mark.asyncio
async def test_one_failing_account_does_not_stop_the_others(monkeypatch):
    repo = FakeUsageRepo()
    calls: list[str] = []

    async def fetch(credential: str) -> AnthropicUsageApiSnapshot:
        calls.append(credential)
        if credential.endswith("bad"):
            raise RuntimeError("boom")
        return _windows_snapshot()

    monkeypatch.setattr(usage_poller, "fetch_anthropic_usage", fetch)

    outcome = await poll_anthropic_usage(
        [_account("first", token=b"bad"), _account("second", token=b"good")],
        encryptor=FakeEncryptor(),
        usage_repo_factory=_repo_factory(repo),
    )

    assert len(calls) == 2
    assert outcome.failed == 1
    assert outcome.written == 1
    assert {w.account_id for w in repo.writes} == {"second"}


@pytest.mark.asyncio
async def test_an_unreadable_credential_is_skipped_not_raised(monkeypatch):
    repo = FakeUsageRepo()
    monkeypatch.setattr(usage_poller, "fetch_anthropic_usage", _fetch_returning(_windows_snapshot()))

    outcome = await poll_anthropic_usage(
        [_account("broken", token=b"rotten")],
        encryptor=FakeEncryptor(raises_for={"rotten"}),
        usage_repo_factory=_repo_factory(repo),
    )

    assert outcome.failed == 1
    assert outcome.polled == 0
    assert repo.writes == []


@pytest.mark.asyncio
async def test_an_empty_snapshot_writes_nothing(monkeypatch):
    repo = FakeUsageRepo()
    monkeypatch.setattr(usage_poller, "fetch_anthropic_usage", _fetch_returning(AnthropicUsageApiSnapshot()))

    outcome = await poll_anthropic_usage(
        [_account()],
        encryptor=FakeEncryptor(),
        usage_repo_factory=_repo_factory(repo),
    )

    assert outcome.polled == 1
    assert outcome.written == 0
    assert repo.writes == []


@pytest.mark.asyncio
async def test_a_persistence_failure_is_contained(monkeypatch):
    monkeypatch.setattr(usage_poller, "fetch_anthropic_usage", _fetch_returning(_windows_snapshot()))

    @contextlib.asynccontextmanager
    async def failing_factory():
        raise RuntimeError("db gone")
        yield  # pragma: no cover

    outcome = await poll_anthropic_usage(
        [_account()],
        encryptor=FakeEncryptor(),
        usage_repo_factory=failing_factory,
    )

    assert outcome.failed == 1
    assert outcome.written == 0


def _fetch_returning(snapshot: AnthropicUsageApiSnapshot):
    async def fetch(credential: str) -> AnthropicUsageApiSnapshot:
        return snapshot

    return fetch


def _fetch_raising(error: Exception):
    async def fetch(credential: str) -> AnthropicUsageApiSnapshot:
        raise error

    return fetch


@pytest.mark.asyncio
async def test_an_unchanged_snapshot_is_not_rewritten_every_tick(monkeypatch):
    """Most accounts are idle most of the time; restating their row is waste."""
    repo = FakeUsageRepo()
    monkeypatch.setattr(usage_poller, "fetch_anthropic_usage", _fetch_returning(_windows_snapshot()))

    for _ in range(3):
        await poll_anthropic_usage(
            [_account()],
            encryptor=FakeEncryptor(),
            usage_repo_factory=_repo_factory(repo),
        )

    assert [(w.window, w.used_percent) for w in repo.writes] == [("primary", 100.0), ("secondary", 27.0)]


@pytest.mark.asyncio
async def test_a_changed_snapshot_is_written_immediately(monkeypatch):
    """The throttle must never defer news -- that is the whole point of polling."""
    repo = FakeUsageRepo()
    snapshots = iter([_windows_snapshot(primary=100.0), _windows_snapshot(primary=3.0)])

    async def fetch(credential: str) -> AnthropicUsageApiSnapshot:
        return next(snapshots)

    monkeypatch.setattr(usage_poller, "fetch_anthropic_usage", fetch)

    for _ in range(2):
        await poll_anthropic_usage(
            [_account()],
            encryptor=FakeEncryptor(),
            usage_repo_factory=_repo_factory(repo),
        )

    assert [w.used_percent for w in repo.writes if w.window == "primary"] == [100.0, 3.0]


@pytest.mark.asyncio
async def test_an_unchanged_snapshot_is_rewritten_once_the_interval_lapses(monkeypatch):
    """Consumers read `recorded_at` as proof the account is still reporting."""
    repo = FakeUsageRepo()
    monkeypatch.setattr(usage_poller, "fetch_anthropic_usage", _fetch_returning(_windows_snapshot()))
    clock = [1000.0]
    monkeypatch.setattr(usage_poller.time, "monotonic", lambda: clock[0])

    await poll_anthropic_usage([_account()], encryptor=FakeEncryptor(), usage_repo_factory=_repo_factory(repo))
    clock[0] += usage_poller.UNCHANGED_WRITE_INTERVAL_SECONDS + 1
    await poll_anthropic_usage([_account()], encryptor=FakeEncryptor(), usage_repo_factory=_repo_factory(repo))

    assert len([w for w in repo.writes if w.window == "primary"]) == 2

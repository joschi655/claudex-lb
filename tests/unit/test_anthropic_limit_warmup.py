from __future__ import annotations

from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from datetime import timedelta
from typing import Any, cast
from unittest.mock import patch

import pytest

from app.core.anthropic.warmup import ANTHROPIC_WARMUP_MODEL
from app.core.providers import PROVIDER_ANTHROPIC, PROVIDER_OPENAI
from app.core.utils.time import naive_utc_to_epoch, utcnow
from app.db.models import Account, AccountStatus, DashboardSettings, UsageHistory
from app.modules.limit_warmup import service as warmup_service
from app.modules.limit_warmup.service import (
    LIMIT_WARMUP_REQUEST_KIND,
    LimitWarmupSendResult,
    LimitWarmupService,
    ProviderLimitWarmupSender,
)
from tests.unit.test_limit_warmup import FakeRequestLogsRepo, FakeWarmupRepo, _settings

pytestmark = pytest.mark.unit


def _anthropic_account(
    account_id: str = "anthropic-1",
    *,
    enabled: bool = True,
    status: AccountStatus = AccountStatus.ACTIVE,
) -> Account:
    return Account(
        id=account_id,
        chatgpt_account_id=None,
        email=f"{account_id}@example.com",
        plan_type="max",
        provider=PROVIDER_ANTHROPIC,
        access_token_encrypted=b"access",
        refresh_token_encrypted=b"refresh",
        id_token_encrypted=None,
        last_refresh=utcnow(),
        status=status,
        deactivation_reason=None,
        limit_warmup_enabled=enabled,
    )


def _primary_window(account_id: str, *, reset_at: int | None, used_percent: float = 96.0) -> UsageHistory:
    return UsageHistory(
        account_id=account_id,
        used_percent=used_percent,
        reset_at=reset_at,
        window="primary",
        window_minutes=300,
        recorded_at=utcnow(),
    )


def _secondary_window(account_id: str, *, reset_at: int | None, used_percent: float = 40.0) -> UsageHistory:
    return UsageHistory(
        account_id=account_id,
        used_percent=used_percent,
        reset_at=reset_at,
        window="secondary",
        window_minutes=10080,
        recorded_at=utcnow(),
    )


def _epoch_now() -> int:
    return naive_utc_to_epoch(utcnow())


@contextmanager
def _clock_advanced_by(delta: timedelta) -> Iterator[None]:
    """Move the warmup service's clock forward.

    Patched in the service module rather than at the source, so both the cooldown
    check and the closed-window key see the same later moment.
    """
    real = warmup_service.utcnow
    with patch.object(warmup_service, "utcnow", lambda: real() + delta):
        yield


class RecordingSender:
    """Captures what warmup asked for, and answers with a canned result."""

    def __init__(self, result: LimitWarmupSendResult | None = None) -> None:
        self.calls: list[tuple[str, str, str]] = []
        self._result = result

    async def send(self, account: Account, *, model: str, prompt: str) -> LimitWarmupSendResult:
        self.calls.append((account.id, model, prompt))
        if self._result is not None:
            return self._result
        return LimitWarmupSendResult(request_id="req-1", success=True, latency_ms=5)


class RecordingIngestor:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, str]]] = []

    async def __call__(self, account_id: str, headers: Mapping[str, str]) -> None:
        self.calls.append((account_id, dict(headers)))


def _service(
    *,
    sender: Any,
    warmup_repo: FakeWarmupRepo | None = None,
    logs: FakeRequestLogsRepo | None = None,
    ingestor: Any = None,
) -> tuple[LimitWarmupService, FakeWarmupRepo, FakeRequestLogsRepo]:
    repo = warmup_repo or FakeWarmupRepo()
    request_logs = logs or FakeRequestLogsRepo()
    service = LimitWarmupService(
        cast(Any, repo),
        cast(Any, request_logs),
        sender=cast(Any, sender),
        window_ingestor=ingestor,
    )
    return service, repo, request_logs


async def _run(
    service: LimitWarmupService,
    *,
    accounts: list[Account],
    settings: DashboardSettings,
    latest_primary: dict[str, UsageHistory],
    latest_secondary: dict[str, UsageHistory] | None = None,
) -> None:
    await service.run_anthropic_window_refresh(
        accounts=accounts,
        settings=settings,
        latest_primary=latest_primary,
        latest_secondary=latest_secondary,
    )


@pytest.mark.asyncio
async def test_elapsed_window_is_warmed() -> None:
    account = _anthropic_account()
    sender = RecordingSender()
    service, repo, logs = _service(sender=sender)

    await _run(
        service,
        accounts=[account],
        settings=_settings(),
        latest_primary={account.id: _primary_window(account.id, reset_at=_epoch_now() - 60)},
    )

    assert sender.calls == [(account.id, ANTHROPIC_WARMUP_MODEL, "Say OK.")]
    assert [row.status for row in repo.rows] == ["succeeded"]
    assert logs.logs[0]["request_kind"] == LIMIT_WARMUP_REQUEST_KIND
    assert logs.logs[0]["model"] == ANTHROPIC_WARMUP_MODEL


@pytest.mark.asyncio
async def test_window_still_open_is_left_alone() -> None:
    account = _anthropic_account()
    sender = RecordingSender()
    service, repo, _ = _service(sender=sender)

    await _run(
        service,
        accounts=[account],
        settings=_settings(),
        latest_primary={account.id: _primary_window(account.id, reset_at=_epoch_now() + 3600)},
    )

    assert sender.calls == []
    assert repo.rows == []


@pytest.mark.asyncio
async def test_a_window_that_is_not_running_is_warmed() -> None:
    """The usage API reports a spent window as utilization 0 with no reset.

    That is the state warmup exists to leave, so it must be a candidate --
    before the poll existed, the only signal was a stale reset in the past.
    """
    account = _anthropic_account()
    sender = RecordingSender()
    service, repo, _ = _service(sender=sender)

    await _run(
        service,
        accounts=[account],
        settings=_settings(),
        latest_primary={account.id: _primary_window(account.id, reset_at=None, used_percent=0.0)},
    )

    assert sender.calls == [(account.id, ANTHROPIC_WARMUP_MODEL, "Say OK.")]
    assert [row.status for row in repo.rows] == ["succeeded"]


@pytest.mark.asyncio
async def test_a_closed_weekly_window_is_warmed_while_the_five_hour_window_runs() -> None:
    """The case the five-hour trigger cannot see.

    A weekly window is anchored to the account's first request exactly like the
    short one, so leaving it unstarted pushes the next weekly reset out by
    however long the account stays idle. The five-hour window running is no
    reason to leave that alone.
    """
    account = _anthropic_account()
    sender = RecordingSender()
    service, repo, _ = _service(sender=sender)

    await _run(
        service,
        accounts=[account],
        settings=_settings(),
        latest_primary={account.id: _primary_window(account.id, reset_at=_epoch_now() + 3600)},
        latest_secondary={account.id: _secondary_window(account.id, reset_at=None, used_percent=0.0)},
    )

    assert sender.calls == [(account.id, ANTHROPIC_WARMUP_MODEL, "Say OK.")]
    # Filed under its own window, so it dedupes against weekly state rather than
    # against whatever the five-hour trigger last did.
    assert [(row.window, row.status) for row in repo.rows] == [("secondary", "succeeded")]


@pytest.mark.asyncio
async def test_an_elapsed_weekly_reset_is_warmed() -> None:
    """The pre-poll signal for a closed window: a reset timestamp in the past."""
    account = _anthropic_account()
    sender = RecordingSender()
    service, repo, _ = _service(sender=sender)

    await _run(
        service,
        accounts=[account],
        settings=_settings(),
        latest_primary={account.id: _primary_window(account.id, reset_at=_epoch_now() + 3600)},
        latest_secondary={account.id: _secondary_window(account.id, reset_at=_epoch_now() - 60)},
    )

    assert [call[0] for call in sender.calls] == [account.id]
    assert [row.window for row in repo.rows] == ["secondary"]


@pytest.mark.asyncio
async def test_a_running_weekly_window_is_left_alone() -> None:
    account = _anthropic_account()
    sender = RecordingSender()
    service, repo, _ = _service(sender=sender)

    await _run(
        service,
        accounts=[account],
        settings=_settings(),
        latest_primary={account.id: _primary_window(account.id, reset_at=_epoch_now() + 3600)},
        latest_secondary={account.id: _secondary_window(account.id, reset_at=_epoch_now() + 86400)},
    )

    assert sender.calls == []
    assert repo.rows == []


@pytest.mark.asyncio
async def test_two_closed_windows_cost_one_ping() -> None:
    """One request opens every closed window, so the weekly one rides along."""
    account = _anthropic_account()
    sender = RecordingSender()
    service, repo, _ = _service(sender=sender)

    await _run(
        service,
        accounts=[account],
        settings=_settings(),
        latest_primary={account.id: _primary_window(account.id, reset_at=None, used_percent=0.0)},
        latest_secondary={account.id: _secondary_window(account.id, reset_at=None, used_percent=0.0)},
    )

    assert len(sender.calls) == 1
    assert [row.window for row in repo.rows] == ["primary"]


@pytest.mark.asyncio
async def test_a_seat_with_no_weekly_window_is_not_warmed_for_one() -> None:
    """A usage-based seat records no weekly window either."""
    account = _anthropic_account()
    sender = RecordingSender()
    service, repo, _ = _service(sender=sender)

    await _run(
        service,
        accounts=[account],
        settings=_settings(),
        latest_primary={account.id: _primary_window(account.id, reset_at=_epoch_now() + 3600)},
        latest_secondary={},
    )

    assert sender.calls == []
    assert repo.rows == []


@pytest.mark.asyncio
async def test_a_caller_that_omits_weekly_state_keeps_the_five_hour_trigger() -> None:
    account = _anthropic_account()
    sender = RecordingSender()
    service, repo, _ = _service(sender=sender)

    await _run(
        service,
        accounts=[account],
        settings=_settings(),
        latest_primary={account.id: _primary_window(account.id, reset_at=_epoch_now() - 60)},
    )

    assert [row.window for row in repo.rows] == ["primary"]


@pytest.mark.asyncio
async def test_the_chatgpt_pass_leaves_claude_accounts_alone() -> None:
    """Regression: the ChatGPT pass filed a bogus attempt that cost a real warm-up.

    ``run_after_usage_refresh`` reasons about ChatGPT usage-API snapshots and
    resolves a model from the OpenAI registry, but its caller hands it every
    account. For a Claude seat the model lookup finds nothing and records a
    `skipped` attempt keyed on that window's *next* reset — which then occupies
    the key the Anthropic pass needs when the window actually closes.

    Observed live: julius crossed 100%, its five-hour window rolled to a reset at
    15:39, and the ChatGPT pass immediately booked that timestamp.
    """
    account = _anthropic_account()
    sender = RecordingSender()
    service, repo, _ = _service(sender=sender)
    now = _epoch_now()
    spent = {account.id: _primary_window(account.id, reset_at=now - 60, used_percent=100.0)}
    reset = {account.id: _primary_window(account.id, reset_at=now + 18_000, used_percent=0.0)}

    await service.run_after_usage_refresh(
        accounts=[account],
        settings=_settings(),
        before_primary=spent,
        before_secondary={},
        after_primary=reset,
        after_secondary={},
    )

    assert sender.calls == []
    assert repo.rows == []


@pytest.mark.asyncio
async def test_a_closed_window_is_warmed_again_in_a_later_period() -> None:
    """Regression: the closed-window trigger used to fire once per account, ever.

    A closed window has no reset timestamp, and the constant that stood in for
    one made the attempt table's dedupe guard permanent — the first attempt an
    account made against a closed window blocked every later one. Observed live:
    an account went 46 hours with a dead five-hour window because a *pending*
    attempt from three days earlier still held the key.
    """
    account = _anthropic_account()
    sender = RecordingSender()
    repo = FakeWarmupRepo()
    service, _, _ = _service(sender=sender, warmup_repo=repo)
    settings = _settings(limit_warmup_cooldown_seconds=3600)
    closed = {account.id: _primary_window(account.id, reset_at=None, used_percent=0.0)}

    await _run(service, accounts=[account], settings=settings, latest_primary=closed)
    assert len(sender.calls) == 1

    # Same period: still one attempt, which is what the guard is for.
    await _run(service, accounts=[account], settings=settings, latest_primary=closed)
    assert len(sender.calls) == 1

    # A later period re-arms the trigger instead of locking it out forever.
    with _clock_advanced_by(timedelta(hours=2)):
        await _run(service, accounts=[account], settings=settings, latest_primary=closed)
    assert len(sender.calls) == 2
    assert [row.reset_at for row in repo.rows][0] != [row.reset_at for row in repo.rows][1]


@pytest.mark.asyncio
async def test_a_stale_pending_attempt_does_not_lock_the_account_out() -> None:
    """The live failure exactly: a never-completed attempt held the only key."""
    account = _anthropic_account()
    sender = RecordingSender()
    repo = FakeWarmupRepo()
    # The row that poisoned matlab: window 'primary', the old constant key,
    # left 'pending' by a restart mid-flight days earlier.
    await repo.try_create_attempt(
        account_id=account.id,
        window="primary",
        reset_at=0,
        model=ANTHROPIC_WARMUP_MODEL,
        attempted_at=utcnow() - timedelta(days=3),
    )
    service, _, _ = _service(sender=sender, warmup_repo=repo)

    await _run(
        service,
        accounts=[account],
        settings=_settings(),
        latest_primary={account.id: _primary_window(account.id, reset_at=None, used_percent=0.0)},
    )

    assert [call[0] for call in sender.calls] == [account.id]


@pytest.mark.asyncio
async def test_a_weekly_ping_does_not_delay_the_next_five_hour_ping() -> None:
    """The two windows close on unrelated schedules, so they cool down apart.

    A weekly reset at 07:00 says nothing about when the five hours run out.
    Charging the weekly ping against the five-hour window would hold the next
    short window closed for up to a full cooldown — a fifth of its length.
    """
    account = _anthropic_account()
    sender = RecordingSender()
    repo = FakeWarmupRepo()
    service, _, _ = _service(sender=sender, warmup_repo=repo)
    settings = _settings(limit_warmup_cooldown_seconds=3600)

    # Weekly closes first, while the five-hour window is still running.
    await _run(
        service,
        accounts=[account],
        settings=settings,
        latest_primary={account.id: _primary_window(account.id, reset_at=_epoch_now() + 1800)},
        latest_secondary={account.id: _secondary_window(account.id, reset_at=None, used_percent=0.0)},
    )
    assert [row.window for row in repo.rows] == ["secondary"]

    # Half an hour later — inside the cooldown — the five hours run out.
    await _run(
        service,
        accounts=[account],
        settings=settings,
        latest_primary={account.id: _primary_window(account.id, reset_at=_epoch_now() - 60)},
        latest_secondary={account.id: _secondary_window(account.id, reset_at=_epoch_now() + 600_000)},
    )

    assert [row.window for row in repo.rows] == ["secondary", "primary"]
    assert len(sender.calls) == 2


@pytest.mark.asyncio
async def test_a_failed_ping_is_not_retried_against_the_other_window() -> None:
    """Per-window cooldowns must not double the ping rate when a ping fails."""
    account = _anthropic_account()
    sender = RecordingSender(
        LimitWarmupSendResult(request_id="req-1", success=False, latency_ms=5, error_code="overloaded_error")
    )
    repo = FakeWarmupRepo()
    service, _, _ = _service(sender=sender, warmup_repo=repo)
    settings = _settings(limit_warmup_cooldown_seconds=3600)
    both_closed = {
        "latest_primary": {account.id: _primary_window(account.id, reset_at=None, used_percent=0.0)},
        "latest_secondary": {account.id: _secondary_window(account.id, reset_at=None, used_percent=0.0)},
    }

    await _run(service, accounts=[account], settings=settings, **both_closed)
    await _run(service, accounts=[account], settings=settings, **both_closed)

    # The five-hour window wins on precedence every tick, so the retry waits on
    # its own cooldown rather than falling through to the weekly window.
    assert len(sender.calls) == 1
    assert [row.window for row in repo.rows] == ["primary"]


@pytest.mark.asyncio
async def test_account_without_a_window_is_never_warmed() -> None:
    """A usage-based seat records no five-hour window, so there is none to open."""
    account = _anthropic_account()
    sender = RecordingSender()
    service, repo, _ = _service(sender=sender)

    await _run(service, accounts=[account], settings=_settings(), latest_primary={})

    assert sender.calls == []
    assert repo.rows == []


@pytest.mark.asyncio
async def test_per_account_toggle_off_is_not_warmed() -> None:
    account = _anthropic_account(enabled=False)
    sender = RecordingSender()
    service, _, _ = _service(sender=sender)

    await _run(
        service,
        accounts=[account],
        settings=_settings(),
        latest_primary={account.id: _primary_window(account.id, reset_at=_epoch_now() - 60)},
    )

    assert sender.calls == []


@pytest.mark.asyncio
async def test_global_setting_off_is_not_warmed() -> None:
    account = _anthropic_account()
    sender = RecordingSender()
    service, _, _ = _service(sender=sender)

    await _run(
        service,
        accounts=[account],
        settings=_settings(limit_warmup_enabled=False),
        latest_primary={account.id: _primary_window(account.id, reset_at=_epoch_now() - 60)},
    )

    assert sender.calls == []


@pytest.mark.asyncio
async def test_paused_claude_account_is_still_warmed() -> None:
    """A parked account has to come back with a live window, not a spent one."""
    account = _anthropic_account(status=AccountStatus.PAUSED)
    sender = RecordingSender()
    service, _, _ = _service(sender=sender)

    await _run(
        service,
        accounts=[account],
        settings=_settings(),
        latest_primary={account.id: _primary_window(account.id, reset_at=_epoch_now() - 60)},
    )

    assert [call[0] for call in sender.calls] == [account.id]


@pytest.mark.asyncio
async def test_paused_openai_account_is_not_warmed() -> None:
    """The relaxation is Claude-only; a paused ChatGPT account stays silent."""
    account = Account(
        id="openai-paused",
        chatgpt_account_id="chatgpt_paused",
        email="openai-paused@example.com",
        plan_type="plus",
        provider=PROVIDER_OPENAI,
        access_token_encrypted=b"access",
        refresh_token_encrypted=b"refresh",
        id_token_encrypted=None,
        last_refresh=utcnow(),
        status=AccountStatus.PAUSED,
        deactivation_reason=None,
        limit_warmup_enabled=True,
    )
    sender = RecordingSender()
    service, _, _ = _service(sender=sender)

    await _run(
        service,
        accounts=[account],
        settings=_settings(),
        latest_primary={account.id: _primary_window(account.id, reset_at=_epoch_now() - 60)},
    )

    assert sender.calls == []


@pytest.mark.asyncio
async def test_openai_accounts_are_not_swept_by_the_anthropic_pass() -> None:
    account = Account(
        id="openai-1",
        chatgpt_account_id="chatgpt_1",
        email="openai-1@example.com",
        plan_type="plus",
        provider=PROVIDER_OPENAI,
        access_token_encrypted=b"access",
        refresh_token_encrypted=b"refresh",
        id_token_encrypted=b"id",
        last_refresh=utcnow(),
        status=AccountStatus.ACTIVE,
        deactivation_reason=None,
        limit_warmup_enabled=True,
    )
    sender = RecordingSender()
    service, _, _ = _service(sender=sender)

    await _run(
        service,
        accounts=[account],
        settings=_settings(),
        latest_primary={account.id: _primary_window(account.id, reset_at=_epoch_now() - 60)},
    )

    assert sender.calls == []


@pytest.mark.asyncio
async def test_cooldown_blocks_a_second_ping() -> None:
    account = _anthropic_account()
    sender = RecordingSender()
    repo = FakeWarmupRepo()
    await repo.try_create_attempt(
        account_id=account.id,
        window="primary",
        reset_at=_epoch_now() - 7200,
        model=ANTHROPIC_WARMUP_MODEL,
        attempted_at=utcnow(),
    )
    service, _, _ = _service(sender=sender, warmup_repo=repo)

    await _run(
        service,
        accounts=[account],
        settings=_settings(limit_warmup_cooldown_seconds=3600),
        latest_primary={account.id: _primary_window(account.id, reset_at=_epoch_now() - 60)},
    )

    assert sender.calls == []


@pytest.mark.asyncio
async def test_warmup_response_headers_are_ingested() -> None:
    account = _anthropic_account()
    sender = RecordingSender(
        LimitWarmupSendResult(
            request_id="req-1",
            success=True,
            latency_ms=5,
            usage_headers={"anthropic-ratelimit-unified-5h-utilization": "0.0"},
        )
    )
    ingestor = RecordingIngestor()
    service, _, _ = _service(sender=sender, ingestor=ingestor)

    await _run(
        service,
        accounts=[account],
        settings=_settings(),
        latest_primary={account.id: _primary_window(account.id, reset_at=_epoch_now() - 60)},
    )

    assert ingestor.calls == [(account.id, {"anthropic-ratelimit-unified-5h-utilization": "0.0"})]


@pytest.mark.asyncio
async def test_response_without_headers_still_succeeds() -> None:
    account = _anthropic_account()
    sender = RecordingSender(LimitWarmupSendResult(request_id="req-1", success=True, latency_ms=5))
    ingestor = RecordingIngestor()
    service, repo, _ = _service(sender=sender, ingestor=ingestor)

    await _run(
        service,
        accounts=[account],
        settings=_settings(),
        latest_primary={account.id: _primary_window(account.id, reset_at=_epoch_now() - 60)},
    )

    assert ingestor.calls == []
    assert [row.status for row in repo.rows] == ["succeeded"]


@pytest.mark.asyncio
async def test_failed_warmup_records_the_error_and_touches_nothing_else() -> None:
    account = _anthropic_account()
    sender = RecordingSender(
        LimitWarmupSendResult(
            request_id="req-1",
            success=False,
            latency_ms=5,
            error_code="overloaded_error",
            error_message="upstream busy",
        )
    )
    service, repo, logs = _service(sender=sender)

    await _run(
        service,
        accounts=[account],
        settings=_settings(),
        latest_primary={account.id: _primary_window(account.id, reset_at=_epoch_now() - 60)},
    )

    assert [row.status for row in repo.rows] == ["failed"]
    assert repo.rows[0].error_code == "overloaded_error"
    assert logs.logs[0]["status"] == "error"
    # Warmup is discretionary traffic: a failure must not touch account health.
    assert account.status == AccountStatus.ACTIVE


@pytest.mark.asyncio
async def test_manual_warmup_runs_with_the_scheduler_switched_off() -> None:
    account = _anthropic_account()
    sender = RecordingSender()
    service, repo, _ = _service(sender=sender)

    result = await service.warm_account_now(account=account, settings=_settings(limit_warmup_enabled=False))

    assert result.sent is True
    assert result.success is True
    assert result.model == ANTHROPIC_WARMUP_MODEL
    assert sender.calls == [(account.id, ANTHROPIC_WARMUP_MODEL, "Say OK.")]
    # Filed under its own window so it cannot be confused with a scheduled attempt.
    assert repo.rows[0].window == "primary_manual"


@pytest.mark.asyncio
async def test_manual_warmup_refuses_a_second_concurrent_attempt() -> None:
    account = _anthropic_account()
    sender = RecordingSender()
    service, _, _ = _service(sender=sender)
    settings = _settings()

    first = await service.warm_account_now(account=account, settings=settings)
    second = await service.warm_account_now(account=account, settings=settings)

    assert first.sent is True
    # Same-second retry hits the attempt table's uniqueness guard.
    assert second.sent is False
    assert second.error_code == "warmup_already_in_flight"
    assert len(sender.calls) == 1


@pytest.mark.asyncio
async def test_provider_dispatch_keeps_each_credential_on_its_own_protocol() -> None:
    openai_sender = RecordingSender()
    anthropic_sender = RecordingSender()
    dispatcher = ProviderLimitWarmupSender(cast(Any, openai_sender), cast(Any, anthropic_sender))

    await dispatcher.send(_anthropic_account(), model="gpt-5.1-codex-mini", prompt="Say OK.")
    assert anthropic_sender.calls == [("anthropic-1", ANTHROPIC_WARMUP_MODEL, "Say OK.")]
    assert openai_sender.calls == []

    openai_account = Account(
        id="openai-1",
        chatgpt_account_id="chatgpt_1",
        email="openai-1@example.com",
        plan_type="plus",
        provider=PROVIDER_OPENAI,
        access_token_encrypted=b"access",
        refresh_token_encrypted=b"refresh",
        id_token_encrypted=b"id",
        last_refresh=utcnow(),
        status=AccountStatus.ACTIVE,
        deactivation_reason=None,
        limit_warmup_enabled=True,
    )
    await dispatcher.send(openai_account, model="gpt-5.1-codex-mini", prompt="Say OK.")
    assert openai_sender.calls == [("openai-1", "gpt-5.1-codex-mini", "Say OK.")]
    assert len(anthropic_sender.calls) == 1

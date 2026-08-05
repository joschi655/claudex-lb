from __future__ import annotations

from collections.abc import Mapping
from typing import Any, cast

import pytest

from app.core.anthropic.warmup import ANTHROPIC_WARMUP_MODEL
from app.core.providers import PROVIDER_ANTHROPIC, PROVIDER_OPENAI
from app.core.utils.time import naive_utc_to_epoch, utcnow
from app.db.models import Account, AccountStatus, DashboardSettings, UsageHistory
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


def _primary_window(account_id: str, *, reset_at: int, used_percent: float = 96.0) -> UsageHistory:
    return UsageHistory(
        account_id=account_id,
        used_percent=used_percent,
        reset_at=reset_at,
        window="primary",
        window_minutes=300,
        recorded_at=utcnow(),
    )


def _epoch_now() -> int:
    return naive_utc_to_epoch(utcnow())


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
) -> None:
    await service.run_anthropic_window_refresh(
        accounts=accounts,
        settings=settings,
        latest_primary=latest_primary,
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

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator, Mapping
from contextlib import AbstractAsyncContextManager
from types import SimpleNamespace
from typing import Any, cast

import pytest
from starlette.responses import StreamingResponse

from app.core.crypto import TokenEncryptor
from app.core.providers import CREDENTIAL_ANTHROPIC_API_KEY, PROVIDER_ANTHROPIC
from app.core.utils.time import utcnow
from app.db.models import Account, AccountStatus
from app.modules.anthropic_proxy import service as service_module
from app.modules.anthropic_proxy.service import AnthropicProxyService
from app.modules.api_keys.service import ApiKeyData, LimitRuleData
from app.modules.proxy.load_balancer import AccountSelection

pytestmark = pytest.mark.unit


def _account(account_id: str) -> Account:
    encryptor = TokenEncryptor()
    return Account(
        id=account_id,
        provider=PROVIDER_ANTHROPIC,
        credential_kind=CREDENTIAL_ANTHROPIC_API_KEY,
        email=f"{account_id}@api-key.local",
        alias=account_id,
        plan_type="claude_api",
        access_token_encrypted=encryptor.encrypt(f"sk-ant-api-{account_id}"),
        refresh_token_encrypted=encryptor.encrypt(""),
        id_token_encrypted=None,
        last_refresh=utcnow(),
        status=AccountStatus.ACTIVE,
    )


def _api_key(*limits: LimitRuleData) -> ApiKeyData:
    return ApiKeyData(
        id="client-key",
        name="Client key",
        key_prefix="clb_test",
        allowed_models=None,
        enforced_model=None,
        enforced_reasoning_effort=None,
        enforced_service_tier=None,
        expires_at=None,
        is_active=True,
        created_at=utcnow(),
        last_used_at=None,
        limits=list(limits),
    )


def _limit(*, limit_type: str, model_filter: str | None = None) -> LimitRuleData:
    return LimitRuleData(
        id=1,
        limit_type=limit_type,
        limit_window="daily",
        max_value=1_000_000,
        current_value=0,
        model_filter=model_filter,
        reset_at=utcnow(),
    )


class _Balancer:
    def __init__(self, accounts: list[Account]) -> None:
        self.accounts = accounts
        self.successes: list[str] = []
        self.errors: list[str] = []
        self.rate_limited: list[tuple[str, dict[str, Any]]] = []
        self.invalidated: list[str] = []
        self.selection_kwargs: list[dict[str, Any]] = []

    async def select_account(self, **kwargs: Any) -> AccountSelection:
        self.selection_kwargs.append(kwargs)
        excluded = set(kwargs.get("exclude_account_ids") or ())
        scoped = kwargs.get("account_ids")
        for account in self.accounts:
            if account.id in excluded or account.status != AccountStatus.ACTIVE:
                continue
            if scoped is not None and account.id not in scoped:
                continue
            return AccountSelection(account=account, error_message=None)
        return AccountSelection(account=None, error_message="No accounts available")

    async def record_success(self, account: Account) -> None:
        self.successes.append(account.id)

    async def record_error(self, account: Account) -> None:
        self.errors.append(account.id)

    async def mark_rate_limit(self, account: Account, error: dict[str, Any]) -> None:
        self.rate_limited.append((account.id, error))
        account.status = AccountStatus.RATE_LIMITED

    async def mark_permanent_failure(self, account: Account, code: str) -> bool:
        del code
        self.invalidated.append(account.id)
        account.status = AccountStatus.REAUTH_REQUIRED
        return True


class _Upstream:
    def __init__(
        self,
        status: int,
        *,
        headers: Mapping[str, str] | None = None,
        body: bytes = b"",
        chunks: list[bytes] | None = None,
    ) -> None:
        self.status = status
        self.headers = dict(headers or {})
        self.body = body
        self.chunks = chunks or []
        self.closed = False

    async def read(self) -> bytes:
        return self.body

    async def aiter_chunked(self, chunk_size: int) -> AsyncIterator[bytes]:
        del chunk_size
        for chunk in self.chunks:
            yield chunk

    async def aclose(self) -> None:
        self.closed = True


class _ReadFailureUpstream(_Upstream):
    async def read(self) -> bytes:
        raise OSError("upstream body interrupted")


class _CloseFailureUpstream(_Upstream):
    async def aclose(self) -> None:
        self.closed = True
        raise OSError("upstream close failed")


def _service(
    monkeypatch: pytest.MonkeyPatch,
    accounts: list[Account],
    outcomes: list[_Upstream | BaseException],
    *,
    routing_strategy: str = "capacity_weighted",
    single_account_id: str | None = None,
) -> tuple[AnthropicProxyService, _Balancer, list[dict[str, str]]]:
    balancer = _Balancer(accounts)
    sent_headers: list[dict[str, str]] = []

    async def open_messages(url: str, *, body: bytes, headers: Mapping[str, str], idle_timeout_seconds: float):
        del url, body, idle_timeout_seconds
        sent_headers.append(dict(headers))
        outcome = outcomes.pop(0)
        if isinstance(outcome, BaseException):
            raise outcome
        return outcome

    class _SettingsCache:
        async def get(self) -> Any:
            return SimpleNamespace(routing_strategy=routing_strategy, single_account_id=single_account_id)

    monkeypatch.setattr(service_module, "open_messages", open_messages)
    monkeypatch.setattr(service_module, "get_settings_cache", lambda: _SettingsCache())
    return AnthropicProxyService(cast(Any, balancer)), balancer, sent_headers


async def _relay(
    service: AnthropicProxyService,
    *,
    upstream_path: str = "/v1/messages",
    api_key: ApiKeyData | None = None,
    body: bytes = b'{"model":"claude-sonnet-5","stream":true,"max_tokens":64}',
) -> Any:
    return await service.relay(
        upstream_path=upstream_path,
        client_headers={"content-type": "application/json", "authorization": "Bearer proxy-key"},
        body=body,
        api_key=api_key,
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("model_filter", [None, "claude-sonnet-5"])
async def test_applicable_cost_limit_rejects_unpriced_claude_before_upstream(
    monkeypatch: pytest.MonkeyPatch,
    model_filter: str | None,
) -> None:
    service, balancer, sent = _service(monkeypatch, [_account("one")], [])

    async def unexpected_reserve(*args: Any, **kwargs: Any) -> Any:
        del args, kwargs
        pytest.fail("cost-limited Claude request must fail before reservation")

    monkeypatch.setattr(service, "_reserve", unexpected_reserve)

    response = await _relay(
        service,
        api_key=_api_key(_limit(limit_type="cost_usd", model_filter=model_filter)),
    )

    assert response.status_code == 403
    assert "Anthropic pricing is unavailable" in json.loads(response.body)["error"]["message"]
    assert balancer.selection_kwargs == []
    assert sent == []


@pytest.mark.asyncio
async def test_nonmatching_cost_limit_does_not_block_claude(monkeypatch: pytest.MonkeyPatch) -> None:
    service, _, sent = _service(
        monkeypatch,
        [_account("one")],
        [_Upstream(200, headers={"content-type": "application/json"}, body=b'{"id":"ok"}')],
    )

    response = await _relay(
        service,
        api_key=_api_key(_limit(limit_type="cost_usd", model_filter="claude-opus-5")),
    )

    assert response.status_code == 200
    assert len(sent) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("upstream_path", "expected_output_tokens"),
    [("/v1/messages", 64), ("/v1/messages/count_tokens", 0)],
)
async def test_reservation_output_budget_depends_on_endpoint(
    monkeypatch: pytest.MonkeyPatch,
    upstream_path: str,
    expected_output_tokens: int,
) -> None:
    captured_budgets: list[Any] = []

    class _ApiKeysService:
        def __init__(self, repository: object) -> None:
            del repository

        async def enforce_limits_for_request(self, key_id: str, **kwargs: Any) -> Any:
            assert key_id == "client-key"
            captured_budgets.append(kwargs["request_usage_budget"])
            return SimpleNamespace(reservation_id="reservation")

    class _RepoContext(AbstractAsyncContextManager[Any]):
        async def __aenter__(self) -> Any:
            return SimpleNamespace(api_keys=object())

        async def __aexit__(self, exc_type: Any, exc_value: Any, traceback: Any) -> None:
            del exc_type, exc_value, traceback

    monkeypatch.setattr(service_module, "ApiKeysService", _ApiKeysService)
    service = AnthropicProxyService(cast(Any, _Balancer([])), repo_factory=_RepoContext)

    reservation = await service._reserve(
        _api_key(),
        service_module._RequestMetadata(model="claude-sonnet-5", max_tokens=64),
        b'{"model":"claude-sonnet-5","max_tokens":64}',
        upstream_path=upstream_path,
    )

    assert reservation == service_module._Reservation("reservation")
    assert captured_budgets[0].output_tokens == expected_output_tokens


@pytest.mark.asyncio
async def test_success_streams_original_bytes_and_uses_console_key(monkeypatch: pytest.MonkeyPatch) -> None:
    upstream = _Upstream(
        200,
        headers={"Content-Type": "text/event-stream"},
        chunks=[b"event: message_start\n\n", b"event: message_stop\n\n"],
    )
    service, balancer, sent = _service(monkeypatch, [_account("one")], [upstream])

    response = await _relay(service)

    assert isinstance(response, StreamingResponse)
    body = b""
    async for chunk in response.body_iterator:
        body += cast(bytes, chunk)
    assert body == b"event: message_start\n\nevent: message_stop\n\n"
    assert sent == [{"content-type": "application/json", "x-api-key": "sk-ant-api-one"}]
    assert balancer.successes == ["one"]
    assert upstream.closed


@pytest.mark.asyncio
async def test_stream_close_failure_still_settles_and_logs(monkeypatch: pytest.MonkeyPatch) -> None:
    upstream = _CloseFailureUpstream(
        200,
        headers={"content-type": "text/event-stream"},
        chunks=[b'event: message_delta\r\ndata: {"usage":{"output_tokens":5}}\r\n\r\n'],
    )
    service, _, _ = _service(monkeypatch, [_account("one")], [upstream])
    settled: list[tuple[int, bool]] = []
    logged: list[tuple[int, str]] = []

    async def settle(reservation: Any, model: str, usage: Any, *, success: bool) -> None:
        del reservation, model
        settled.append((usage.output_tokens, success))

    async def write_log(**kwargs: Any) -> None:
        logged.append((kwargs["usage"].output_tokens, kwargs["status"]))

    monkeypatch.setattr(service, "_settle", settle)
    monkeypatch.setattr(service, "_write_log", write_log)

    response = await _relay(service)
    assert isinstance(response, StreamingResponse)
    with pytest.raises(OSError, match="upstream close failed"):
        async for _ in response.body_iterator:
            pass

    assert upstream.closed is True
    assert settled == [(5, True)]
    assert logged == [(5, "success")]


@pytest.mark.asyncio
async def test_mid_stream_upstream_failure_degrades_account_and_settles(monkeypatch: pytest.MonkeyPatch) -> None:
    account = _account("one")
    upstream = _Upstream(200, headers={"content-type": "text/event-stream"}, chunks=[])

    async def interrupted_chunks(chunk_size: int) -> AsyncIterator[bytes]:
        del chunk_size
        yield b"event: message_start\n\n"
        raise OSError("stream reset")

    cast(Any, upstream).aiter_chunked = interrupted_chunks
    service, balancer, _ = _service(monkeypatch, [account], [upstream])
    settled: list[bool] = []

    async def settle(reservation: Any, model: str, usage: Any, *, success: bool) -> None:
        del reservation, model, usage
        settled.append(success)

    monkeypatch.setattr(service, "_settle", settle)

    response = await _relay(service)
    assert isinstance(response, StreamingResponse)
    with pytest.raises(OSError, match="stream reset"):
        async for _ in response.body_iterator:
            pass

    assert balancer.errors == [account.id]
    assert settled == [False]
    assert upstream.closed is True


@pytest.mark.asyncio
async def test_connect_error_fails_over(monkeypatch: pytest.MonkeyPatch) -> None:
    service, balancer, _ = _service(
        monkeypatch,
        [_account("one"), _account("two")],
        [OSError("dns"), _Upstream(200, headers={"content-type": "application/json"}, body=b'{"id":"ok"}')],
    )

    response = await _relay(service)

    assert response.status_code == 200
    assert balancer.errors == ["one"]
    assert balancer.successes == ["two"]


@pytest.mark.asyncio
async def test_failover_logs_failed_attempt_then_final_success(monkeypatch: pytest.MonkeyPatch) -> None:
    service, _, _ = _service(
        monkeypatch,
        [_account("one"), _account("two")],
        [OSError("dns"), _Upstream(200, headers={"content-type": "application/json"}, body=b'{"id":"ok"}')],
    )
    logged: list[tuple[str | None, str, str | None]] = []

    async def write_log(**kwargs: Any) -> None:
        account = kwargs["account"]
        logged.append((account.id if account is not None else None, kwargs["status"], kwargs["error_code"]))

    monkeypatch.setattr(service, "_write_log", write_log)

    assert (await _relay(service)).status_code == 200
    assert logged == [
        ("one", "error", "OSError"),
        ("two", "success", None),
    ]


@pytest.mark.asyncio
async def test_settings_failure_settles_existing_reservation(monkeypatch: pytest.MonkeyPatch) -> None:
    service, _, _ = _service(monkeypatch, [_account("one")], [])
    reservation = service_module._Reservation("reservation-settings-failure")

    async def reserve(*args: Any, **kwargs: Any) -> Any:
        del args, kwargs
        return reservation

    settled: list[tuple[str, bool]] = []

    async def settle(
        current: Any,
        model: str,
        usage: Any,
        *,
        success: bool,
    ) -> None:
        del model, usage
        settled.append((current.reservation_id, success))

    class _FailingSettingsCache:
        async def get(self) -> Any:
            raise RuntimeError("settings unavailable")

    monkeypatch.setattr(service, "_reserve", reserve)
    monkeypatch.setattr(service, "_settle", settle)
    monkeypatch.setattr(service_module, "get_settings_cache", lambda: _FailingSettingsCache())

    with pytest.raises(RuntimeError, match="settings unavailable"):
        await _relay(service)

    assert settled == [(reservation.reservation_id, False)]


@pytest.mark.asyncio
async def test_error_body_read_failure_closes_and_fails_over(monkeypatch: pytest.MonkeyPatch) -> None:
    interrupted = _ReadFailureUpstream(500)
    service, balancer, _ = _service(
        monkeypatch,
        [_account("one"), _account("two")],
        [interrupted, _Upstream(200, headers={"content-type": "application/json"}, body=b'{"id":"ok"}')],
    )

    response = await _relay(service)

    assert response.status_code == 200
    assert interrupted.closed is True
    assert balancer.errors == ["one"]
    assert balancer.successes == ["two"]


@pytest.mark.asyncio
async def test_empty_success_stream_fails_over_before_commit(monkeypatch: pytest.MonkeyPatch) -> None:
    service, balancer, _ = _service(
        monkeypatch,
        [_account("one"), _account("two")],
        [
            _Upstream(200, headers={"content-type": "text/event-stream"}, chunks=[]),
            _Upstream(200, headers={"content-type": "application/json"}, body=b'{"id":"ok"}'),
        ],
    )

    response = await _relay(service)

    assert response.status_code == 200
    assert balancer.errors == ["one"]
    assert balancer.successes == ["two"]


@pytest.mark.asyncio
async def test_429_parses_rfc3339_reset_and_fails_over(monkeypatch: pytest.MonkeyPatch) -> None:
    service, balancer, _ = _service(
        monkeypatch,
        [_account("one"), _account("two")],
        [
            _Upstream(
                429,
                headers={
                    "anthropic-ratelimit-requests-remaining": "0",
                    "anthropic-ratelimit-requests-reset": "2030-01-02T03:04:05Z",
                },
                body=b'{"type":"error","error":{"message":"slow down"}}',
            ),
            _Upstream(200, headers={"content-type": "application/json"}, body=b'{"id":"ok"}'),
        ],
    )

    assert (await _relay(service)).status_code == 200
    assert balancer.rate_limited[0][1]["resets_at"] == 1_893_553_445


@pytest.mark.asyncio
async def test_429_uses_latest_exhausted_bucket_reset(monkeypatch: pytest.MonkeyPatch) -> None:
    service, balancer, _ = _service(
        monkeypatch,
        [_account("one"), _account("two")],
        [
            _Upstream(
                429,
                headers={
                    "anthropic-ratelimit-tokens-remaining": "5",
                    "anthropic-ratelimit-tokens-reset": "2030-01-02T03:00:00Z",
                    "anthropic-ratelimit-requests-remaining": "0",
                    "anthropic-ratelimit-requests-reset": "2030-01-02T03:04:05Z",
                    "anthropic-ratelimit-input-tokens-remaining": "0",
                    "anthropic-ratelimit-input-tokens-reset": "2030-01-02T03:05:00Z",
                },
                body=b'{"type":"error","error":{"message":"slow down"}}',
            ),
            _Upstream(200, headers={"content-type": "application/json"}, body=b'{"id":"ok"}'),
        ],
    )

    assert (await _relay(service)).status_code == 200
    assert balancer.rate_limited[0][1]["resets_at"] == 1_893_553_500


@pytest.mark.asyncio
async def test_429_prefers_explicit_retry_after(monkeypatch: pytest.MonkeyPatch) -> None:
    service, balancer, _ = _service(
        monkeypatch,
        [_account("one"), _account("two")],
        [
            _Upstream(
                429,
                headers={
                    "retry-after": "17",
                    "anthropic-ratelimit-requests-remaining": "0",
                    "anthropic-ratelimit-requests-reset": "2030-01-02T03:04:05Z",
                },
                body=b'{"type":"error","error":{"message":"slow down"}}',
            ),
            _Upstream(200, headers={"content-type": "application/json"}, body=b'{"id":"ok"}'),
        ],
    )

    assert (await _relay(service)).status_code == 200
    assert balancer.rate_limited[0][1]["resets_in_seconds"] == 17
    assert "resets_at" not in balancer.rate_limited[0][1]


@pytest.mark.asyncio
async def test_401_invalidates_without_refresh(monkeypatch: pytest.MonkeyPatch) -> None:
    service, balancer, sent = _service(
        monkeypatch,
        [_account("one"), _account("two")],
        [
            _Upstream(401, body=b'{"type":"error","error":{"message":"invalid key"}}'),
            _Upstream(200, headers={"content-type": "application/json"}, body=b'{"id":"ok"}'),
        ],
    )

    assert (await _relay(service)).status_code == 200
    assert balancer.invalidated == ["one"]
    assert len(sent) == 2


@pytest.mark.asyncio
async def test_terminal_failed_attempt_is_logged_once(monkeypatch: pytest.MonkeyPatch) -> None:
    service, _, _ = _service(
        monkeypatch,
        [_account("one")],
        [_Upstream(401, body=b'{"type":"error","error":{"message":"invalid key"}}')],
    )
    logged: list[tuple[str, str | None]] = []

    async def write_log(**kwargs: Any) -> None:
        logged.append((kwargs["status"], kwargs["error_code"]))

    monkeypatch.setattr(service, "_write_log", write_log)

    assert (await _relay(service)).status_code == 401
    assert logged == [("error", "account_auth_invalidated")]


@pytest.mark.asyncio
async def test_sse_error_event_settles_and_logs_failure_without_replay(monkeypatch: pytest.MonkeyPatch) -> None:
    upstream = _Upstream(
        200,
        headers={"content-type": "text/event-stream"},
        chunks=[
            b'event: message_start\ndata: {"message":{"usage":{"input_tokens":3}}}\n\n',
            b'event: error\ndata: {"type":"error","error":{"type":"overloaded_error",'
            b'"message":"capacity unavailable"}}\n\n',
        ],
    )
    service, balancer, _ = _service(monkeypatch, [_account("one"), _account("two")], [upstream])
    settled: list[tuple[int, bool]] = []
    logged: list[tuple[str, str | None, str | None]] = []

    async def settle(reservation: Any, model: str, usage: Any, *, success: bool) -> None:
        del reservation, model
        settled.append((usage.input_tokens, success))

    async def write_log(**kwargs: Any) -> None:
        logged.append((kwargs["status"], kwargs["error_code"], kwargs["error_message"]))

    monkeypatch.setattr(service, "_settle", settle)
    monkeypatch.setattr(service, "_write_log", write_log)

    response = await _relay(service)
    assert isinstance(response, StreamingResponse)
    async for _ in response.body_iterator:
        pass

    assert settled == [(3, False)]
    assert logged == [("error", "overloaded_error", "capacity unavailable")]
    assert balancer.errors == ["one"]
    assert len(balancer.selection_kwargs) == 1


@pytest.mark.asyncio
async def test_permission_403_does_not_invalidate_on_oauth_word(monkeypatch: pytest.MonkeyPatch) -> None:
    body = b'{"type":"error","error":{"message":"OAuth clients cannot use this feature"}}'
    service, balancer, _ = _service(monkeypatch, [_account("one")], [_Upstream(403, body=body)])

    response = await _relay(service)

    assert response.status_code == 403
    assert response.body == body
    assert balancer.invalidated == []


@pytest.mark.asyncio
async def test_single_account_configuration_is_exact(monkeypatch: pytest.MonkeyPatch) -> None:
    service, balancer, _ = _service(
        monkeypatch,
        [_account("one"), _account("two")],
        [_Upstream(200, headers={"content-type": "application/json"}, body=b'{"id":"ok"}')],
        routing_strategy="single_account",
        single_account_id="two",
    )

    assert (await _relay(service)).status_code == 200
    assert balancer.selection_kwargs[0]["account_ids"] == {"two"}


@pytest.mark.asyncio
async def test_no_accounts_returns_anthropic_429(monkeypatch: pytest.MonkeyPatch) -> None:
    service, _, _ = _service(monkeypatch, [], [])

    response = await _relay(service)

    assert response.status_code == 429
    assert json.loads(response.body)["error"]["type"] == "rate_limit_error"


@pytest.mark.asyncio
async def test_drain_persistence_tasks_waits_for_rate_limit_writes(monkeypatch: pytest.MonkeyPatch) -> None:
    service, _, _ = _service(monkeypatch, [], [])
    gate = asyncio.Event()

    async def wait_for_gate() -> None:
        await gate.wait()

    task = asyncio.create_task(wait_for_gate(), name="anthropic-rate-limit:test")
    service._usage_tasks.add(task)
    task.add_done_callback(service._usage_tasks.discard)

    assert await service.drain_persistence_tasks(timeout_seconds=0.01) is False
    gate.set()
    assert await service.drain_persistence_tasks(timeout_seconds=1) is True

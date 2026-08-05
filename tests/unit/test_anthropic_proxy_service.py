from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator, Mapping
from dataclasses import dataclass
from types import SimpleNamespace
from typing import Any, cast

import pytest
from starlette.responses import StreamingResponse

from app.core.anthropic.client_identity import CLAUDE_CODE_SYSTEM_TEXT, CLAUDE_CODE_USER_AGENT
from app.core.crypto import TokenEncryptor
from app.core.providers import PROVIDER_ANTHROPIC
from app.core.utils.time import utcnow
from app.db.models import Account, AccountStatus
from app.modules.anthropic_proxy import service as anthropic_service_module
from app.modules.anthropic_proxy.service import AnthropicProxyService
from app.modules.proxy.load_balancer import AccountSelection

pytestmark = pytest.mark.unit


def _make_account(account_id: str, *, credential: str = "sk-ant-oat01-token") -> Account:
    encryptor = TokenEncryptor()
    return Account(
        id=account_id,
        provider=PROVIDER_ANTHROPIC,
        email=f"{account_id}@example.com",
        plan_type="claude_max",
        access_token_encrypted=encryptor.encrypt(credential),
        refresh_token_encrypted=encryptor.encrypt("sk-ant-ort01-refresh"),
        id_token_encrypted=None,
        access_token_expires_at=4_000_000_000,
        last_refresh=utcnow(),
        status=AccountStatus.ACTIVE,
        deactivation_reason=None,
    )


class _FakeLoadBalancer:
    def __init__(self, accounts: list[Account]) -> None:
        self._accounts = accounts
        self.successes: list[str] = []
        self.rate_limited: list[tuple[str, dict[str, Any]]] = []
        self.permanent_failures: list[tuple[str, str]] = []
        self.errors: list[str] = []
        self.selection_kwargs: list[dict[str, Any]] = []

    async def select_account(self, **kwargs: Any) -> AccountSelection:
        assert kwargs["provider"] == PROVIDER_ANTHROPIC
        self.selection_kwargs.append(dict(kwargs))
        excluded = set(kwargs.get("exclude_account_ids") or ())
        for account in self._accounts:
            if account.id not in excluded and account.status == AccountStatus.ACTIVE:
                return AccountSelection(account=account, error_message=None)
        return AccountSelection(account=None, error_message="No accounts available")

    async def record_success(self, account: Account) -> None:
        self.successes.append(account.id)

    async def mark_rate_limit(self, account: Account, error: dict[str, Any]) -> None:
        self.rate_limited.append((account.id, error))
        account.status = AccountStatus.RATE_LIMITED

    async def mark_permanent_failure(self, account: Account, code: str) -> bool:
        self.permanent_failures.append((account.id, code))
        account.status = AccountStatus.REAUTH_REQUIRED
        return True

    async def record_error(self, account: Account) -> None:
        self.errors.append(account.id)


class _FakeUpstreamResponse:
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
        self._body = body
        self._chunks = chunks or []
        self.closed = False

    async def read(self) -> bytes:
        return self._body

    async def aiter_chunked(self, chunk_size: int) -> AsyncIterator[bytes]:
        for chunk in self._chunks:
            yield chunk

    async def aclose(self) -> None:
        self.closed = True


@dataclass(frozen=True, slots=True)
class _SentRequest:
    """What actually went out on the wire for one upstream attempt."""

    headers: dict[str, str]
    body: bytes


def _build_service(
    monkeypatch: pytest.MonkeyPatch,
    accounts: list[Account],
    outcomes: list[_FakeUpstreamResponse],
    *,
    routing_strategy: str = "capacity_weighted",
) -> tuple[AnthropicProxyService, _FakeLoadBalancer, list[_SentRequest]]:
    balancer = _FakeLoadBalancer(accounts)
    sent: list[_SentRequest] = []

    async def _fake_open_messages(url: str, *, body: bytes, headers: Mapping[str, str], idle_timeout_seconds: float):
        sent.append(_SentRequest(headers=dict(headers), body=body))
        return outcomes.pop(0)

    monkeypatch.setattr(anthropic_service_module, "open_messages", _fake_open_messages)

    # The relay resolves the operator routing strategy from the dashboard
    # settings cache; keep unit tests DB-free with a canned settings object.
    class _FakeSettingsCache:
        async def get(self) -> Any:
            return SimpleNamespace(routing_strategy=routing_strategy)

    monkeypatch.setattr(anthropic_service_module, "get_settings_cache", lambda: _FakeSettingsCache())

    service = AnthropicProxyService(
        load_balancer=cast(Any, balancer),
        accounts_repo_factory=cast(Any, None),
    )

    async def _fake_ensure_fresh(account: Account, *, force: bool = False) -> Account:
        return account

    monkeypatch.setattr(service, "_ensure_fresh", _fake_ensure_fresh)
    return service, balancer, sent


async def _relay(
    service: AnthropicProxyService,
    *,
    client_headers: Mapping[str, str] | None = None,
    body: bytes = b'{"model": "claude-sonnet-5"}',
) -> Any:
    return await service.relay(
        upstream_path="/v1/messages",
        client_headers=dict(
            client_headers or {"content-type": "application/json", "authorization": "Bearer proxy-key"}
        ),
        body=body,
    )


@pytest.mark.asyncio
async def test_success_streams_bytes_verbatim(monkeypatch):
    upstream = _FakeUpstreamResponse(
        200,
        headers={"content-type": "text/event-stream", "anthropic-ratelimit-unified-5h-remaining": "42"},
        chunks=[b"event: message_start\n\n", b"event: message_stop\n\n"],
    )
    service, balancer, sent = _build_service(monkeypatch, [_make_account("acc-1")], [upstream])

    response = await _relay(service)

    assert isinstance(response, StreamingResponse)
    collected = b""
    async for chunk in response.body_iterator:
        collected += cast(bytes, chunk)
    assert collected == b"event: message_start\n\nevent: message_stop\n\n"
    assert upstream.closed
    assert balancer.successes == ["acc-1"]
    # Client proxy key never reaches upstream; account token injected.
    assert sent[0].headers["Authorization"] == "Bearer sk-ant-oat01-token"
    assert response.headers["anthropic-ratelimit-unified-5h-remaining"] == "42"


@pytest.mark.asyncio
async def test_429_marks_rate_limited_and_fails_over(monkeypatch):
    first = _FakeUpstreamResponse(
        429,
        headers={"anthropic-ratelimit-unified-reset": "1900000000"},
        body=b'{"type":"error","error":{"type":"rate_limit_error","message":"limit"}}',
    )
    second = _FakeUpstreamResponse(
        200,
        headers={"content-type": "application/json"},
        body=b'{"id":"msg_1"}',
    )
    service, balancer, sent = _build_service(
        monkeypatch, [_make_account("acc-1"), _make_account("acc-2")], [first, second]
    )

    response = await _relay(service)

    assert response.status_code == 200
    assert response.body == b'{"id":"msg_1"}'
    assert [entry[0] for entry in balancer.rate_limited] == ["acc-1"]
    assert balancer.rate_limited[0][1]["resets_at"] == 1_900_000_000
    assert balancer.successes == ["acc-2"]
    assert len(sent) == 2


@pytest.mark.asyncio
async def test_401_forces_one_refresh_then_degrades(monkeypatch):
    auth_error = b'{"type":"error","error":{"type":"authentication_error","message":"bad token"}}'
    outcomes = [
        _FakeUpstreamResponse(401, body=auth_error),
        _FakeUpstreamResponse(401, body=auth_error),
        _FakeUpstreamResponse(200, headers={"content-type": "application/json"}, body=b'{"id":"msg_2"}'),
    ]
    service, balancer, sent = _build_service(monkeypatch, [_make_account("acc-1"), _make_account("acc-2")], outcomes)

    force_calls: list[str] = []

    async def _fake_ensure_fresh(account: Account, *, force: bool = False) -> Account:
        if force:
            force_calls.append(account.id)
        return account

    monkeypatch.setattr(service, "_ensure_fresh", _fake_ensure_fresh)

    response = await _relay(service)

    assert response.status_code == 200
    # Exactly one forced refresh for acc-1, then permanent failure, then failover.
    assert force_calls == ["acc-1"]
    assert balancer.permanent_failures == [("acc-1", "account_auth_invalidated")]
    assert balancer.successes == ["acc-2"]
    assert len(sent) == 3


@pytest.mark.asyncio
async def test_client_4xx_returns_verbatim_without_health_writes(monkeypatch):
    validation = _FakeUpstreamResponse(
        400,
        headers={"content-type": "application/json"},
        body=b'{"type":"error","error":{"type":"invalid_request_error","message":"bad request"}}',
    )
    service, balancer, _ = _build_service(monkeypatch, [_make_account("acc-1")], [validation])

    response = await _relay(service)

    assert response.status_code == 400
    assert b"invalid_request_error" in response.body
    assert balancer.rate_limited == []
    assert balancer.permanent_failures == []
    assert balancer.errors == []


@pytest.mark.asyncio
async def test_5xx_records_error_and_fails_over(monkeypatch):
    outcomes = [
        _FakeUpstreamResponse(500, body=b'{"type":"error","error":{"type":"api_error","message":"boom"}}'),
        _FakeUpstreamResponse(200, headers={"content-type": "application/json"}, body=b'{"id":"msg_3"}'),
    ]
    service, balancer, _ = _build_service(monkeypatch, [_make_account("acc-1"), _make_account("acc-2")], outcomes)

    response = await _relay(service)

    assert response.status_code == 200
    assert balancer.errors == ["acc-1"]
    assert balancer.successes == ["acc-2"]


@pytest.mark.asyncio
async def test_all_accounts_exhausted_returns_last_upstream_error(monkeypatch):
    error_body = b'{"type":"error","error":{"type":"rate_limit_error","message":"limit"}}'
    outcomes = [
        _FakeUpstreamResponse(429, headers={"retry-after": "60"}, body=error_body),
        _FakeUpstreamResponse(429, headers={"retry-after": "120"}, body=error_body),
    ]
    service, balancer, _ = _build_service(monkeypatch, [_make_account("acc-1"), _make_account("acc-2")], outcomes)

    response = await _relay(service)

    assert response.status_code == 429
    assert response.body == error_body
    assert [entry[0] for entry in balancer.rate_limited] == ["acc-1", "acc-2"]


@pytest.mark.asyncio
async def test_no_accounts_returns_anthropic_shaped_429(monkeypatch):
    service, _, _ = _build_service(monkeypatch, [], [])

    response = await _relay(service)

    assert response.status_code == 429
    payload = json.loads(response.body)
    assert payload["type"] == "error"
    assert payload["error"]["type"] == "rate_limit_error"
    # Retry hint so clients back off instead of hot-retrying.
    assert response.headers["retry-after"] == "30"


@pytest.mark.asyncio
async def test_relay_uses_configured_routing_strategy(monkeypatch):
    upstream = _FakeUpstreamResponse(200, headers={"content-type": "application/json"}, body=b'{"id":"msg_rs"}')
    service, balancer, _ = _build_service(
        monkeypatch, [_make_account("acc-1")], [upstream], routing_strategy="sequential_drain"
    )

    response = await _relay(service)

    assert response.status_code == 200
    assert balancer.selection_kwargs[0]["routing_strategy"] == "sequential_drain"


@pytest.mark.asyncio
async def test_429_response_ingests_usage_headers(monkeypatch):
    saturated = _FakeUpstreamResponse(
        429,
        headers={
            "anthropic-ratelimit-unified-5h-utilization": "1.0",
            "anthropic-ratelimit-unified-5h-reset": "1900000000",
        },
        body=b'{"type":"error","error":{"type":"rate_limit_error","message":"limit"}}',
    )
    service, balancer, _ = _build_service(monkeypatch, [_make_account("acc-1")], [saturated])

    written: list[tuple[str, Any]] = []

    async def _fake_write_usage(account_id: str, snapshot: Any) -> None:
        written.append((account_id, snapshot))

    monkeypatch.setattr(service, "_write_usage", _fake_write_usage)

    response = await _relay(service)
    await asyncio.gather(*list(service._usage_tasks))

    assert response.status_code == 429
    assert [entry[0] for entry in balancer.rate_limited] == ["acc-1"]
    assert len(written) == 1
    assert written[0][0] == "acc-1"
    assert written[0][1].primary_used_percent == 100.0
    assert written[0][1].primary_reset_at == 1_900_000_000


@pytest.mark.asyncio
async def test_oauth_relay_presents_the_caller_as_claude_code(monkeypatch):
    """A non-Claude-Code caller reaches upstream wearing the Claude Code
    fingerprint: the OAuth token the pool spends was issued against it."""
    upstream = _FakeUpstreamResponse(200, headers={"content-type": "application/json"}, body=b'{"id":"msg_id"}')
    service, _, sent = _build_service(monkeypatch, [_make_account("acc-1")], [upstream])

    await _relay(
        service,
        client_headers={"content-type": "application/json", "user-agent": "hermes-agent/1.0"},
        body=b'{"model":"claude-sonnet-5","system":"You are Hermes."}',
    )

    assert sent[0].headers["user-agent"] == CLAUDE_CODE_USER_AGENT
    assert sent[0].headers["x-app"] == "cli"
    system = json.loads(sent[0].body)["system"]
    assert system[0] == {"type": "text", "text": CLAUDE_CODE_SYSTEM_TEXT}
    # The caller's own prompt survives, it is only pushed down one block.
    assert system[1] == {"type": "text", "text": "You are Hermes."}


@pytest.mark.asyncio
async def test_static_account_relays_the_body_byte_for_byte(monkeypatch):
    """A console key is not a Claude Code credential, so nothing is disguised."""
    upstream = _FakeUpstreamResponse(200, headers={"content-type": "application/json"}, body=b'{"id":"msg_id"}')
    body = b'{"model":"claude-sonnet-5","system":"You are Hermes."}'
    static_account = _make_account("acc-static", credential="sk-ant-api03-console")
    service, _, sent = _build_service(monkeypatch, [static_account], [upstream])

    await _relay(
        service,
        client_headers={"content-type": "application/json", "user-agent": "hermes-agent/1.0"},
        body=body,
    )

    assert sent[0].body is body
    assert sent[0].headers["user-agent"] == "hermes-agent/1.0"
    assert "x-app" not in sent[0].headers


@pytest.mark.asyncio
async def test_body_is_normalized_once_across_failover(monkeypatch):
    """Normalizing re-serializes; failing over must not pay for it again."""
    outcomes = [
        _FakeUpstreamResponse(429, body=b'{"type":"error","error":{"type":"rate_limit_error","message":"limit"}}'),
        _FakeUpstreamResponse(200, headers={"content-type": "application/json"}, body=b'{"id":"msg_id"}'),
    ]
    service, _, sent = _build_service(monkeypatch, [_make_account("acc-1"), _make_account("acc-2")], outcomes)

    await _relay(service, client_headers={"content-type": "application/json", "user-agent": "hermes-agent/1.0"})

    assert len(sent) == 2
    assert sent[0].body is sent[1].body


@pytest.mark.asyncio
async def test_static_account_401_degrades_without_refresh(monkeypatch):
    auth_error = b'{"type":"error","error":{"type":"authentication_error","message":"revoked"}}'
    outcomes = [_FakeUpstreamResponse(401, body=auth_error)]
    static_account = _make_account("acc-static", credential="sk-ant-api03-console")
    service, balancer, _ = _build_service(monkeypatch, [static_account], outcomes)

    force_calls: list[str] = []

    async def _fake_ensure_fresh(account: Account, *, force: bool = False) -> Account:
        if force:
            force_calls.append(account.id)
        return account

    monkeypatch.setattr(service, "_ensure_fresh", _fake_ensure_fresh)

    response = await _relay(service)

    assert response.status_code == 401
    assert force_calls == []
    assert balancer.permanent_failures == [("acc-static", "account_auth_invalidated")]

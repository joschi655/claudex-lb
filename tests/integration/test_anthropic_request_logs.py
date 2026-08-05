"""Request-log emission from the Anthropic relay.

Contract: openspec/changes/add-anthropic-request-logs/specs/anthropic-provider/spec.md.
"""

from __future__ import annotations

import asyncio
import json
import time
from collections.abc import AsyncIterator, Mapping

import pytest
from sqlalchemy import select

from app.db.models import RequestLog
from app.db.session import SessionLocal
from app.modules.anthropic_proxy import api as anthropic_api_module
from app.modules.anthropic_proxy import service as anthropic_service_module

pytestmark = pytest.mark.integration

_LOG_WAIT_SECONDS = 5.0
_LOG_POLL_SECONDS = 0.02


@pytest.fixture(autouse=True)
def _bypass_proxy_auth(monkeypatch: pytest.MonkeyPatch) -> None:
    async def _allow(authorization, *, request=None):
        del authorization, request
        return None

    monkeypatch.setattr(anthropic_api_module, "validate_proxy_api_key_authorization", _allow)


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


async def _import_claude_account(async_client, email: str) -> None:
    payload = {
        "email": email,
        "claudeAiOauth": {
            "accessToken": f"sk-ant-oat01-{email}",
            "refreshToken": f"sk-ant-ort01-{email}",
            "expiresAt": (int(time.time()) + 8 * 3600) * 1000,
            "subscriptionType": "max",
        },
    }
    files = {"auth_json": ("keychain.json", json.dumps(payload), "application/json")}
    response = await async_client.post("/api/accounts/import", files=files)
    assert response.status_code == 200


def _queue_upstream(monkeypatch: pytest.MonkeyPatch, outcomes: list[_FakeUpstreamResponse]) -> None:
    async def _fake_open_messages(url: str, *, body: bytes, headers: Mapping[str, str], idle_timeout_seconds: float):
        del url, body, headers, idle_timeout_seconds
        return outcomes.pop(0)

    monkeypatch.setattr(anthropic_service_module, "open_messages", _fake_open_messages)


async def _read_logs() -> list[RequestLog]:
    async with SessionLocal() as session:
        result = await session.execute(select(RequestLog).order_by(RequestLog.id))
        return list(result.scalars().all())


async def _wait_for_logs(expected: int) -> list[RequestLog]:
    """Logs are written off the response path, so poll rather than assume."""
    deadline = time.monotonic() + _LOG_WAIT_SECONDS
    logs: list[RequestLog] = []
    while time.monotonic() < deadline:
        logs = await _read_logs()
        if len(logs) >= expected:
            return logs
        await asyncio.sleep(_LOG_POLL_SECONDS)
    raise AssertionError(f"expected {expected} request log(s), saw {len(logs)}")


async def _assert_no_logs() -> None:
    # Give any (incorrectly) spawned write time to land before asserting none.
    await asyncio.sleep(0.2)
    assert await _read_logs() == []


@pytest.mark.asyncio
async def test_successful_completion_is_logged_with_usage(async_client, monkeypatch):
    await _import_claude_account(async_client, "logs-success@example.com")
    _queue_upstream(
        monkeypatch,
        [
            _FakeUpstreamResponse(
                200,
                headers={"content-type": "application/json", "request-id": "req_abc123"},
                body=json.dumps(
                    {
                        "type": "message",
                        "model": "claude-opus-5",
                        "usage": {
                            "input_tokens": 10,
                            "cache_read_input_tokens": 90,
                            "cache_creation_input_tokens": 5,
                            "output_tokens": 42,
                        },
                    }
                ).encode(),
            )
        ],
    )

    response = await async_client.post(
        "/v1/messages",
        headers={"content-type": "application/json", "user-agent": "claude-cli/2.1.0 (external, cli)"},
        content=b'{"model":"claude-sonnet-5"}',
    )
    assert response.status_code == 200

    (log,) = await _wait_for_logs(1)
    assert log.status == "success"
    assert log.error_code is None
    assert log.request_id == "req_abc123"
    # The response names the model actually served, not the requested alias.
    assert log.model == "claude-opus-5"
    assert log.input_tokens == 105
    assert log.cached_input_tokens == 90
    assert log.output_tokens == 42
    assert log.latency_ms is not None
    assert log.useragent == "claude-cli/2.1.0 (external, cli)"
    assert log.useragent_group == "claude-cli"
    assert log.transport == "http"
    # Subscription seats have no marginal per-request price.
    assert log.cost_usd is None
    assert log.account_id is not None


@pytest.mark.asyncio
async def test_streaming_completion_records_first_token_latency(async_client, monkeypatch):
    await _import_claude_account(async_client, "logs-stream@example.com")
    start_event = (
        b"event: message_start\n"
        b'data: {"type":"message_start","message":{"model":"claude-opus-5",'
        b'"usage":{"input_tokens":100,"output_tokens":1}}}\n\n'
    )
    delta_event = (
        b"event: message_delta\n"
        b'data: {"type":"message_delta","delta":{"stop_reason":"end_turn"},"usage":{"output_tokens":250}}\n\n'
    )
    _queue_upstream(
        monkeypatch,
        [
            _FakeUpstreamResponse(
                200,
                headers={"content-type": "text/event-stream"},
                chunks=[start_event, b"event: content_block_delta\n\n", delta_event],
            )
        ],
    )

    async with async_client.stream(
        "POST",
        "/v1/messages",
        headers={"content-type": "application/json"},
        content=b'{"model":"claude-sonnet-5","stream":true}',
    ) as response:
        assert response.status_code == 200
        collected = b""
        async for chunk in response.aiter_bytes():
            collected += chunk

    # Every byte reached the client unchanged despite being parsed in passing.
    assert collected == start_event + b"event: content_block_delta\n\n" + delta_event

    (log,) = await _wait_for_logs(1)
    assert log.status == "success"
    assert log.input_tokens == 100
    assert log.output_tokens == 250
    assert log.latency_first_token_ms is not None


@pytest.mark.asyncio
async def test_count_tokens_is_not_logged(async_client, monkeypatch):
    await _import_claude_account(async_client, "logs-count@example.com")
    _queue_upstream(
        monkeypatch,
        [
            _FakeUpstreamResponse(
                200,
                headers={"content-type": "application/json"},
                body=b'{"input_tokens":123}',
            )
        ],
    )

    response = await async_client.post(
        "/v1/messages/count_tokens",
        headers={"content-type": "application/json"},
        content=b'{"model":"claude-sonnet-5"}',
    )
    assert response.status_code == 200
    await _assert_no_logs()


@pytest.mark.asyncio
async def test_failover_logs_one_row_per_attempt(async_client, monkeypatch):
    await _import_claude_account(async_client, "logs-primary@example.com")
    await _import_claude_account(async_client, "logs-secondary@example.com")
    _queue_upstream(
        monkeypatch,
        [
            _FakeUpstreamResponse(
                429,
                headers={"anthropic-ratelimit-unified-reset": str(int(time.time()) + 300)},
                body=b'{"type":"error","error":{"type":"rate_limit_error","message":"slow down"}}',
            ),
            _FakeUpstreamResponse(
                200,
                headers={"content-type": "application/json"},
                body=json.dumps(
                    {"type": "message", "model": "claude-opus-5", "usage": {"input_tokens": 5, "output_tokens": 6}}
                ).encode(),
            ),
        ],
    )

    response = await async_client.post(
        "/v1/messages",
        headers={"content-type": "application/json"},
        content=b'{"model":"claude-sonnet-5"}',
    )
    assert response.status_code == 200

    logs = await _wait_for_logs(2)
    by_status = {log.status: log for log in logs}
    assert set(by_status) == {"error", "success"}

    failed = by_status["error"]
    assert failed.error_code == "rate_limit_exceeded"
    assert failed.upstream_status_code == 429
    assert failed.error_message == "slow down"
    # The rate-limited attempt names the model that was asked for; no response
    # body was produced to name a served one.
    assert failed.model == "claude-sonnet-5"

    assert by_status["success"].output_tokens == 6
    # The two attempts are attributed to different accounts.
    assert failed.account_id != by_status["success"].account_id


@pytest.mark.asyncio
async def test_client_error_is_logged_and_passed_through(async_client, monkeypatch):
    await _import_claude_account(async_client, "logs-client-error@example.com")
    _queue_upstream(
        monkeypatch,
        [
            _FakeUpstreamResponse(
                400,
                headers={"content-type": "application/json"},
                body=b'{"type":"error","error":{"type":"invalid_request_error","message":"bad model"}}',
            )
        ],
    )

    response = await async_client.post(
        "/v1/messages",
        headers={"content-type": "application/json"},
        content=b'{"model":"claude-sonnet-5"}',
    )
    assert response.status_code == 400

    (log,) = await _wait_for_logs(1)
    assert log.status == "error"
    assert log.error_code == "invalid_request"
    assert log.upstream_status_code == 400
    assert log.error_message == "bad model"


@pytest.mark.asyncio
async def test_log_write_failure_does_not_affect_the_response(async_client, monkeypatch):
    await _import_claude_account(async_client, "logs-write-fail@example.com")
    _queue_upstream(
        monkeypatch,
        [
            _FakeUpstreamResponse(
                200,
                headers={"content-type": "application/json"},
                body=b'{"type":"message","model":"claude-opus-5","usage":{"input_tokens":1,"output_tokens":2}}',
            )
        ],
    )

    class _BrokenRepo:
        def __init__(self, session) -> None:
            del session

        async def add_log(self, **kwargs):
            raise RuntimeError("database is on fire")

    monkeypatch.setattr(anthropic_service_module, "RequestLogsRepository", _BrokenRepo)

    response = await async_client.post(
        "/v1/messages",
        headers={"content-type": "application/json"},
        content=b'{"model":"claude-sonnet-5"}',
    )
    assert response.status_code == 200
    assert response.json()["model"] == "claude-opus-5"
    await _assert_no_logs()

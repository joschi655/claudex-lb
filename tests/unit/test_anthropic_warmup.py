from __future__ import annotations

import json
from typing import Any

import aiohttp
import pytest

from app.core.anthropic import warmup as warmup_module
from app.core.anthropic.warmup import (
    ANTHROPIC_WARMUP_MODEL,
    build_warmup_body,
    build_warmup_headers,
    send_warmup,
)

pytestmark = pytest.mark.unit


class _FakeUpstreamResponse:
    def __init__(self, status: int, body: bytes, headers: dict[str, str] | None = None) -> None:
        self.status = status
        self.headers = headers or {}
        self._body = body
        self.closed = False

    async def read(self) -> bytes:
        return self._body

    async def aclose(self) -> None:
        self.closed = True


def _patch_open_messages(monkeypatch: pytest.MonkeyPatch, response: Any) -> dict[str, Any]:
    captured: dict[str, Any] = {}

    async def fake_open_messages(url: str, *, body: bytes, headers: Any, idle_timeout_seconds: float) -> Any:
        captured["url"] = url
        captured["body"] = body
        captured["headers"] = dict(headers)
        captured["idle_timeout_seconds"] = idle_timeout_seconds
        if isinstance(response, BaseException):
            raise response
        return response

    monkeypatch.setattr(warmup_module, "open_messages", fake_open_messages)
    return captured


def test_warmup_body_is_a_single_token_completion() -> None:
    payload = json.loads(build_warmup_body(ANTHROPIC_WARMUP_MODEL))
    assert payload["model"] == ANTHROPIC_WARMUP_MODEL
    assert payload["max_tokens"] == 1
    assert payload["messages"] == [{"role": "user", "content": "ok"}]
    # OAuth credentials are only accepted on requests presenting as Claude Code.
    assert payload["system"].startswith("You are Claude Code")


def test_warmup_headers_carry_oauth_bearer_and_beta_flag() -> None:
    headers = build_warmup_headers("sk-ant-oat01-example")
    assert headers["Authorization"] == "Bearer sk-ant-oat01-example"
    assert "oauth-2025-04-20" in headers["anthropic-beta"]
    assert headers["anthropic-version"] == "2023-06-01"
    assert "x-api-key" not in headers


def test_warmup_headers_use_api_key_for_a_static_key() -> None:
    headers = build_warmup_headers("sk-ant-api03-example")
    assert headers["x-api-key"] == "sk-ant-api03-example"
    assert "Authorization" not in headers


@pytest.mark.asyncio
async def test_successful_warmup_returns_headers_and_usage(monkeypatch: pytest.MonkeyPatch) -> None:
    response = _FakeUpstreamResponse(
        200,
        json.dumps({"usage": {"input_tokens": 12, "output_tokens": 1}}).encode(),
        {"anthropic-ratelimit-unified-5h-utilization": "0.0"},
    )
    captured = _patch_open_messages(monkeypatch, response)

    result = await send_warmup("sk-ant-oat01-example")

    assert result.success is True
    assert result.status_code == 200
    assert result.input_tokens == 12
    assert result.output_tokens == 1
    assert result.headers["anthropic-ratelimit-unified-5h-utilization"] == "0.0"
    assert captured["url"].endswith("/v1/messages")
    assert response.closed is True


@pytest.mark.asyncio
async def test_error_status_is_a_failed_result_not_an_exception(monkeypatch: pytest.MonkeyPatch) -> None:
    response = _FakeUpstreamResponse(
        429,
        json.dumps({"error": {"type": "rate_limit_error", "message": "slow down"}}).encode(),
        {"anthropic-ratelimit-unified-5h-utilization": "1.0"},
    )
    _patch_open_messages(monkeypatch, response)

    result = await send_warmup("sk-ant-oat01-example")

    assert result.success is False
    assert result.status_code == 429
    assert result.error_code == "rate_limit_error"
    assert result.error_message == "slow down"
    # A 429 still describes the window, so its headers must survive.
    assert result.headers["anthropic-ratelimit-unified-5h-utilization"] == "1.0"
    assert response.closed is True


@pytest.mark.asyncio
async def test_transport_failure_is_reported_as_upstream_unavailable(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_open_messages(monkeypatch, aiohttp.ClientError("connection reset"))

    result = await send_warmup("sk-ant-oat01-example")

    assert result.success is False
    assert result.status_code is None
    assert result.error_code == "upstream_unavailable"


@pytest.mark.asyncio
async def test_timeout_is_reported_as_timeout(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_open_messages(monkeypatch, TimeoutError())

    result = await send_warmup("sk-ant-oat01-example")

    assert result.success is False
    assert result.error_code == "timeout"


@pytest.mark.asyncio
async def test_unparseable_body_does_not_fail_a_successful_ping(monkeypatch: pytest.MonkeyPatch) -> None:
    response = _FakeUpstreamResponse(200, b"not json")
    _patch_open_messages(monkeypatch, response)

    result = await send_warmup("sk-ant-oat01-example")

    assert result.success is True
    assert result.input_tokens is None
    assert result.output_tokens is None

from __future__ import annotations

import aiohttp

from app.core.anthropic import upstream as upstream_module
from app.core.anthropic.upstream import (
    build_upstream_headers,
    filter_response_headers,
    open_messages,
)


def test_console_api_key_replaces_client_auth_and_preserves_headers():
    headers = build_upstream_headers(
        {
            "authorization": "Bearer client-proxy-key",
            "x-api-key": "client-proxy-key",
            "anthropic-version": "2023-06-01",
            "anthropic-beta": "prompt-caching-2024-07-31",
            "content-type": "application/json",
            "host": "proxy.local",
            "content-length": "123",
            "cookie": "session=client-secret",
            "user-agent": "claude-cli/1.0",
        },
        "sk-ant-api03-xyz",
    )
    assert headers["x-api-key"] == "sk-ant-api03-xyz"
    assert "Authorization" not in headers
    assert headers["anthropic-beta"] == "prompt-caching-2024-07-31"
    assert headers["anthropic-version"] == "2023-06-01"
    assert headers["user-agent"] == "claude-cli/1.0"
    assert "host" not in headers
    assert "content-length" not in headers
    assert "cookie" not in headers


def test_console_api_key_does_not_synthesize_oauth_beta():
    headers = build_upstream_headers(
        {"authorization": "Bearer client-proxy-key", "anthropic-version": "2023-06-01"},
        "sk-ant-api03-xyz",
    )
    assert headers["x-api-key"] == "sk-ant-api03-xyz"
    assert "Authorization" not in headers
    assert "anthropic-beta" not in headers


def test_filter_response_headers_drops_hop_by_hop():
    filtered = dict(
        filter_response_headers(
            {
                "content-type": "text/event-stream",
                "anthropic-ratelimit-unified-5h-remaining": "12",
                "transfer-encoding": "chunked",
                "content-length": "42",
                "content-encoding": "gzip",
                "set-cookie": "upstream-session=secret",
            }
        )
    )
    assert filtered["content-type"] == "text/event-stream"
    assert filtered["anthropic-ratelimit-unified-5h-remaining"] == "12"
    assert "transfer-encoding" not in filtered
    assert "content-length" not in filtered
    assert "content-encoding" not in filtered
    assert "set-cookie" not in filtered


async def test_open_messages_uses_idle_timeout_not_total(monkeypatch):
    """The stream timeout is an idle (sock_read) timeout: an actively
    streaming SSE response must never be cut off by a total-duration cap."""
    captured: dict[str, object] = {}

    class _FakeResponse:
        status = 200
        headers: dict[str, str] = {}

        def release(self) -> None:
            pass

    class _FakeSession:
        async def post(self, url, *, data, headers, timeout):
            captured["timeout"] = timeout
            return _FakeResponse()

    class _FakeClient:
        session = _FakeSession()

    class _FakeLease:
        client = _FakeClient()

        async def close(self) -> None:
            pass

    async def _fake_acquire():
        return _FakeLease()

    monkeypatch.setattr(upstream_module, "acquire_http_client", _fake_acquire)

    response = await open_messages(
        "https://api.anthropic.com/v1/messages",
        body=b"{}",
        headers={"content-type": "application/json"},
        idle_timeout_seconds=7200.0,
    )
    await response.aclose()

    timeout = captured["timeout"]
    assert isinstance(timeout, aiohttp.ClientTimeout)
    assert timeout.total is None
    assert timeout.sock_read == 7200.0
    assert timeout.connect == 30.0
    assert timeout.sock_connect == 30.0

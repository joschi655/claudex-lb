from __future__ import annotations

import aiohttp

from app.core.anthropic import upstream as upstream_module
from app.core.anthropic.upstream import (
    build_upstream_headers,
    credential_is_static_api_key,
    filter_response_headers,
    open_messages,
)


def test_oauth_credential_uses_bearer_and_merges_beta():
    headers = build_upstream_headers(
        {
            "authorization": "Bearer client-proxy-key",
            "x-api-key": "client-proxy-key",
            "anthropic-version": "2023-06-01",
            "anthropic-beta": "prompt-caching-2024-07-31",
            "content-type": "application/json",
            "host": "proxy.local",
            "content-length": "123",
            "user-agent": "claude-cli/1.0",
        },
        "sk-ant-oat-abc",
    )
    assert headers["Authorization"] == "Bearer sk-ant-oat-abc"
    assert "x-api-key" not in headers
    # OAuth beta flag merged in without dropping the client's own beta flag.
    assert "prompt-caching-2024-07-31" in headers["anthropic-beta"]
    assert "oauth-2025-04-20" in headers["anthropic-beta"]
    # Passed through untouched.
    assert headers["anthropic-version"] == "2023-06-01"
    assert headers["user-agent"] == "claude-cli/1.0"
    # Hop-by-hop / host / length stripped.
    assert "host" not in headers
    assert "content-length" not in headers


def test_oauth_credential_adds_beta_when_client_sent_none():
    headers = build_upstream_headers({"content-type": "application/json"}, "sk-ant-oat-abc")
    assert headers["anthropic-beta"] == "oauth-2025-04-20"


def test_static_api_key_uses_x_api_key_without_oauth_beta():
    headers = build_upstream_headers(
        {"authorization": "Bearer client-proxy-key", "anthropic-version": "2023-06-01"},
        "sk-ant-api03-xyz",
    )
    assert headers["x-api-key"] == "sk-ant-api03-xyz"
    assert "Authorization" not in headers
    assert "anthropic-beta" not in headers


def test_credential_is_static_api_key():
    assert credential_is_static_api_key("sk-ant-api03-xyz")
    assert not credential_is_static_api_key("sk-ant-oat01-xyz")


def test_filter_response_headers_drops_hop_by_hop():
    filtered = dict(
        filter_response_headers(
            {
                "content-type": "text/event-stream",
                "anthropic-ratelimit-unified-5h-remaining": "12",
                "transfer-encoding": "chunked",
                "content-length": "42",
                "content-encoding": "gzip",
            }
        )
    )
    assert filtered["content-type"] == "text/event-stream"
    assert filtered["anthropic-ratelimit-unified-5h-remaining"] == "12"
    assert "transfer-encoding" not in filtered
    assert "content-length" not in filtered
    assert "content-encoding" not in filtered


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

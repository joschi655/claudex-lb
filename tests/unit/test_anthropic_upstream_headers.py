from __future__ import annotations

import aiohttp

from app.core.anthropic import upstream as upstream_module
from app.core.anthropic.client_identity import ATTRIBUTION_HEADER, CLAUDE_CODE_USER_AGENT
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
    # Already a Claude Code caller: its own version survives, not the pinned one.
    assert headers["user-agent"] == "claude-cli/1.0"
    # Hop-by-hop / host / length stripped.
    assert "host" not in headers
    assert "content-length" not in headers


def test_oauth_credential_adds_beta_when_client_sent_none():
    headers = build_upstream_headers({"content-type": "application/json"}, "sk-ant-oat-abc")
    assert headers["anthropic-beta"] == "oauth-2025-04-20, claude-code-20250219"


def test_oauth_credential_stamps_claude_code_identity_on_other_clients():
    headers = build_upstream_headers(
        {"content-type": "application/json", "user-agent": "hermes-agent/1.0"},
        "sk-ant-oat-abc",
    )
    assert headers["user-agent"] == CLAUDE_CODE_USER_AGENT
    assert headers["x-app"] == "cli"
    assert "oauth-2025-04-20" in headers["anthropic-beta"]
    assert "claude-code-20250219" in headers["anthropic-beta"]


def test_oauth_identity_replaces_client_user_agent_whatever_its_casing():
    """Client headers keep their original casing, so a ``User-Agent`` spelling
    must not survive alongside the injected ``user-agent``."""
    headers = build_upstream_headers(
        {"User-Agent": "hermes-agent/1.0", "content-type": "application/json"},
        "sk-ant-oat-abc",
    )
    agents = [value for key, value in headers.items() if key.lower() == "user-agent"]
    assert agents == [CLAUDE_CODE_USER_AGENT]


def test_lifted_attribution_is_sent_as_the_header_it_is_written_as():
    headers = build_upstream_headers(
        {"content-type": "application/json", "user-agent": "claude-cli/2.1.220 (external, cli)"},
        "sk-ant-oat-abc",
        attribution="cc_version=2.1.220.b7d; cc_entrypoint=claude-vscode; cch=ff2f4;",
    )
    assert headers[ATTRIBUTION_HEADER] == "cc_version=2.1.220.b7d; cc_entrypoint=claude-vscode; cch=ff2f4;"


def test_caller_that_sent_the_attribution_header_itself_keeps_its_own():
    headers = build_upstream_headers(
        {"X-Anthropic-Billing-Header": "cc_version=own;", "content-type": "application/json"},
        "sk-ant-oat-abc",
        attribution="cc_version=lifted;",
    )
    values = [value for key, value in headers.items() if key.lower() == ATTRIBUTION_HEADER]
    assert values == ["cc_version=own;"]


def test_no_attribution_means_no_header():
    headers = build_upstream_headers({"content-type": "application/json"}, "sk-ant-oat-abc")
    assert not any(key.lower() == ATTRIBUTION_HEADER for key in headers)


def test_static_api_key_uses_x_api_key_without_oauth_beta():
    headers = build_upstream_headers(
        {"authorization": "Bearer client-proxy-key", "anthropic-version": "2023-06-01"},
        "sk-ant-api03-xyz",
    )
    assert headers["x-api-key"] == "sk-ant-api03-xyz"
    assert "Authorization" not in headers
    assert "anthropic-beta" not in headers


def test_static_api_key_is_never_disguised_as_claude_code():
    headers = build_upstream_headers(
        {"user-agent": "hermes-agent/1.0", "content-type": "application/json"},
        "sk-ant-api03-xyz",
    )
    assert headers["user-agent"] == "hermes-agent/1.0"
    assert "x-app" not in headers


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

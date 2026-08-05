from __future__ import annotations

import logging
from collections.abc import AsyncIterator, Mapping

import aiohttp

from app.core.anthropic.client_identity import (
    CLAUDE_CODE_APP,
    CLAUDE_CODE_BETA,
    CLAUDE_CODE_USER_AGENT,
    client_presents_as_claude_code,
)
from app.core.anthropic.oauth import ANTHROPIC_OAUTH_BETA
from app.core.clients.http import HttpClientLease, acquire_http_client

logger = logging.getLogger(__name__)

ANTHROPIC_API_BASE = "https://api.anthropic.com"

# Console API keys authenticate with x-api-key; OAuth access tokens use a
# Bearer header plus the OAuth beta flag. Claude Code's OAuth access tokens are
# prefixed sk-ant-oat; static console keys are sk-ant-api.
_STATIC_API_KEY_PREFIX = "sk-ant-api"

# Connection setup gets a short bounded budget; the caller-supplied timeout is
# an IDLE (sock_read) timeout so an actively streaming SSE response is never
# cut off by a total-duration cap.
_CONNECT_TIMEOUT_SECONDS = 30.0

# Client request headers we never forward: client auth (replaced with the
# selected account credential) and hop-by-hop/transport headers.
_STRIPPED_REQUEST_HEADERS = frozenset(
    {
        "authorization",
        "x-api-key",
        "host",
        "content-length",
        "connection",
        "keep-alive",
        "proxy-authenticate",
        "proxy-authorization",
        "te",
        "trailer",
        "transfer-encoding",
        "upgrade",
    }
)

# Upstream response headers we never forward back to the client (hop-by-hop /
# transport). ``anthropic-*`` and rate-limit headers pass through untouched.
_STRIPPED_RESPONSE_HEADERS = frozenset(
    {
        "connection",
        "keep-alive",
        "proxy-authenticate",
        "proxy-authorization",
        "te",
        "trailer",
        "transfer-encoding",
        "upgrade",
        "content-length",
        "content-encoding",
    }
)


def credential_is_static_api_key(credential: str) -> bool:
    return credential.startswith(_STATIC_API_KEY_PREFIX)


def build_upstream_headers(client_headers: Mapping[str, str], credential: str) -> dict[str, str]:
    """Rewrite client request headers for the upstream Anthropic request.

    Strips client auth and hop-by-hop headers and injects the account
    credential. OAuth credentials additionally get the Claude Code fingerprint
    the pool's tokens are issued against: the ``oauth-2025-04-20`` and
    ``claude-code-20250219`` beta flags, ``x-app``, and a ``claude-cli``
    user-agent for callers that are not already Claude Code. Static console keys
    are relayed with the caller's own headers untouched.

    Everything else -- ``anthropic-version``, other ``anthropic-*``,
    ``content-type``, ``accept`` -- passes through as sent.
    """
    headers: dict[str, str] = {}
    client_beta: str | None = None
    for key, value in client_headers.items():
        lowered = key.lower()
        if lowered == "anthropic-beta":
            client_beta = value
            continue
        if lowered in _STRIPPED_REQUEST_HEADERS:
            continue
        headers[key] = value

    if credential_is_static_api_key(credential):
        headers["x-api-key"] = credential
        if client_beta:
            headers["anthropic-beta"] = client_beta
    else:
        headers["Authorization"] = f"Bearer {credential}"
        headers["anthropic-beta"] = _merge_beta(client_beta, ANTHROPIC_OAUTH_BETA, CLAUDE_CODE_BETA)
        _apply_claude_code_headers(headers, client_headers)

    return headers


def _apply_claude_code_headers(headers: dict[str, str], client_headers: Mapping[str, str]) -> None:
    """Stamp the Claude Code client headers onto an OAuth upstream request.

    A caller that already presents as Claude Code keeps its own user-agent --
    its version is real, and the pinned one is not.
    """
    _set_header(headers, "x-app", CLAUDE_CODE_APP)
    if not client_presents_as_claude_code(client_headers):
        _set_header(headers, "user-agent", CLAUDE_CODE_USER_AGENT)


def _set_header(headers: dict[str, str], name: str, value: str) -> None:
    """Set a header, replacing any existing spelling of it.

    Client headers are copied through with their original casing, so a caller's
    ``User-Agent`` would otherwise survive alongside the one being written.
    """
    for existing in [key for key in headers if key.lower() == name]:
        del headers[existing]
    headers[name] = value


def filter_response_headers(response_headers: Mapping[str, str]) -> list[tuple[str, str]]:
    return [(key, value) for key, value in response_headers.items() if key.lower() not in _STRIPPED_RESPONSE_HEADERS]


def _merge_beta(client_beta: str | None, *required: str) -> str:
    flags = [flag.strip() for flag in (client_beta or "").split(",") if flag.strip()]
    for flag in required:
        if flag not in flags:
            flags.append(flag)
    return ", ".join(flags)


class AnthropicUpstreamResponse:
    """An open upstream response whose session lease is released on close.

    The caller inspects ``status``/``headers`` first, then either reads the
    full body (non-stream / error) or iterates ``aiter_chunked`` (SSE). Either
    way it MUST ``aclose`` exactly once so the pooled session lease is returned.
    """

    def __init__(self, response: aiohttp.ClientResponse, lease: HttpClientLease) -> None:
        self._response = response
        self._lease = lease
        self._closed = False

    @property
    def status(self) -> int:
        return self._response.status

    @property
    def headers(self) -> Mapping[str, str]:
        return self._response.headers

    async def read(self) -> bytes:
        return await self._response.read()

    async def aiter_chunked(self, chunk_size: int) -> AsyncIterator[bytes]:
        async for chunk in self._response.content.iter_chunked(chunk_size):
            yield chunk

    async def aclose(self) -> None:
        if self._closed:
            return
        self._closed = True
        self._response.release()
        await self._lease.close()


async def open_messages(
    url: str,
    *,
    body: bytes,
    headers: Mapping[str, str],
    idle_timeout_seconds: float,
) -> AnthropicUpstreamResponse:
    """Open a POST to the upstream Anthropic API, returning the live response.

    The response body is NOT read here so the caller can stream it. On any
    failure before a response object exists, the session lease is released.
    """
    lease = await acquire_http_client()
    session = lease.client.session
    timeout = aiohttp.ClientTimeout(
        total=None,
        connect=_CONNECT_TIMEOUT_SECONDS,
        sock_connect=_CONNECT_TIMEOUT_SECONDS,
        sock_read=idle_timeout_seconds,
    )
    try:
        response = await session.post(url, data=body, headers=dict(headers), timeout=timeout)
    except BaseException:
        await lease.close()
        raise
    return AnthropicUpstreamResponse(response, lease)

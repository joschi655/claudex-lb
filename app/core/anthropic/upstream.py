from __future__ import annotations

import logging
from collections.abc import AsyncIterator, Mapping

import aiohttp

from app.core.clients.http import HttpClientLease, acquire_http_client

logger = logging.getLogger(__name__)

ANTHROPIC_API_BASE = "https://api.anthropic.com"

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
        "cookie",
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
        "set-cookie",
    }
)


def build_upstream_headers(client_headers: Mapping[str, str], credential: str) -> dict[str, str]:
    """Rewrite client request headers for the upstream Anthropic request.

    Strips client auth and hop-by-hop headers, injects the account credential,
    using an Anthropic Console API key. All other client headers --
    ``anthropic-version``, other
    ``anthropic-*``, ``content-type``, ``accept``, the client ``user-agent`` --
    pass through so the upstream sees Claude Code's own fingerprint.
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

    headers["x-api-key"] = credential
    if client_beta:
        headers["anthropic-beta"] = client_beta

    return headers


def filter_response_headers(response_headers: Mapping[str, str]) -> list[tuple[str, str]]:
    return [(key, value) for key, value in response_headers.items() if key.lower() not in _STRIPPED_RESPONSE_HEADERS]


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

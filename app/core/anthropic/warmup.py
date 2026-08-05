"""Open a fresh five-hour window on a Claude account with a one-token request.

A Claude subscription window starts at the account's first request and closes
five hours later, so an idle account keeps a spent window alive indefinitely.
The warmup ping exists only to land: content is irrelevant, ``max_tokens: 1``
against the cheapest model, and what matters is that the clock restarts.

The response's unified rate-limit headers are returned to the caller so the
newly opened window can be ingested through the same path a relayed response
uses.
"""

from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass, field
from typing import Any

import aiohttp

from app.core.anthropic.client_identity import CLAUDE_CODE_SYSTEM_TEXT, CLAUDE_CODE_USER_AGENT
from app.core.anthropic.upstream import ANTHROPIC_API_BASE, build_upstream_headers, open_messages

logger = logging.getLogger(__name__)

# Fixed rather than configurable: the requirement is "the cheapest model that
# opens a window", which has one right answer and nothing to tune.
ANTHROPIC_WARMUP_MODEL = "claude-haiku-4-5-20251001"

# OAuth access tokens are only accepted on requests that present themselves as
# Claude Code, so warmup carries the same system prompt and user agent a relayed
# request does -- shared with the relay via ``client_identity`` so the window a
# warmup opens is attributed to the same identity as the traffic that follows.
_WARMUP_PROMPT = "ok"

_MESSAGES_URL = f"{ANTHROPIC_API_BASE}/v1/messages"
_WARMUP_TIMEOUT_SECONDS = 30.0
# The body is a one-token completion or a small error envelope; anything larger
# is malformed and there is nothing in it worth reading.
_MAX_BODY_BYTES = 64 * 1024


@dataclass(frozen=True, slots=True)
class AnthropicWarmupResult:
    success: bool
    status_code: int | None
    latency_ms: int
    headers: dict[str, str] = field(default_factory=dict)
    input_tokens: int | None = None
    output_tokens: int | None = None
    error_code: str | None = None
    error_message: str | None = None


def build_warmup_body(model: str, *, prompt: str = _WARMUP_PROMPT) -> bytes:
    return json.dumps(
        {
            "model": model,
            "max_tokens": 1,
            "system": CLAUDE_CODE_SYSTEM_TEXT,
            "messages": [{"role": "user", "content": prompt}],
        }
    ).encode()


def build_warmup_headers(credential: str) -> dict[str, str]:
    """Headers for a warmup request.

    There is no client request to rewrite, so the minimum a Messages call needs
    is synthesized and handed to the relay's own header builder — that is what
    picks Bearer-vs-``x-api-key`` and attaches the OAuth beta flag.
    """
    return build_upstream_headers(
        {
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
            "accept": "application/json",
            "user-agent": CLAUDE_CODE_USER_AGENT,
        },
        credential,
    )


async def send_warmup(
    credential: str,
    *,
    model: str = ANTHROPIC_WARMUP_MODEL,
    prompt: str = _WARMUP_PROMPT,
    timeout_seconds: float = _WARMUP_TIMEOUT_SECONDS,
) -> AnthropicWarmupResult:
    """Send one warmup ping and report what came back.

    Never raises for an upstream outcome: a transport failure, a timeout, and an
    error status all return a failed result. Warmup is discretionary traffic and
    must not be able to take down the loop that schedules it.
    """
    started = time.perf_counter()
    response = None
    try:
        response = await open_messages(
            _MESSAGES_URL,
            body=build_warmup_body(model, prompt=prompt),
            headers=build_warmup_headers(credential),
            idle_timeout_seconds=timeout_seconds,
        )
        raw = await response.read()
        headers = {key: value for key, value in response.headers.items()}
        latency_ms = _elapsed_ms(started)
        if response.status >= 400:
            code, message = _parse_error(raw)
            return AnthropicWarmupResult(
                success=False,
                status_code=response.status,
                latency_ms=latency_ms,
                headers=headers,
                error_code=code,
                error_message=message,
            )
        input_tokens, output_tokens = _parse_usage(raw)
        return AnthropicWarmupResult(
            success=True,
            status_code=response.status,
            latency_ms=latency_ms,
            headers=headers,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
        )
    except aiohttp.ClientError as exc:
        return AnthropicWarmupResult(
            success=False,
            status_code=None,
            latency_ms=_elapsed_ms(started),
            error_code="upstream_unavailable",
            error_message=str(exc)[:200],
        )
    except TimeoutError as exc:
        return AnthropicWarmupResult(
            success=False,
            status_code=None,
            latency_ms=_elapsed_ms(started),
            error_code="timeout",
            error_message=str(exc)[:200] or "warmup request timed out",
        )
    finally:
        if response is not None:
            await response.aclose()


def _decode(raw: bytes) -> dict[str, Any] | None:
    if not raw or len(raw) > _MAX_BODY_BYTES:
        return None
    try:
        parsed = json.loads(raw)
    except (ValueError, UnicodeDecodeError):
        return None
    return parsed if isinstance(parsed, dict) else None


def _parse_error(raw: bytes) -> tuple[str | None, str | None]:
    body = _decode(raw)
    error = body.get("error") if body else None
    if not isinstance(error, dict):
        return None, None
    code = error.get("type")
    message = error.get("message")
    return (
        code if isinstance(code, str) else None,
        message[:200] if isinstance(message, str) else None,
    )


def _parse_usage(raw: bytes) -> tuple[int | None, int | None]:
    body = _decode(raw)
    usage = body.get("usage") if body else None
    if not isinstance(usage, dict):
        return None, None
    return _int_or_none(usage.get("input_tokens")), _int_or_none(usage.get("output_tokens"))


def _int_or_none(value: Any) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def _elapsed_ms(started: float) -> int:
    return max(0, int((time.perf_counter() - started) * 1000))

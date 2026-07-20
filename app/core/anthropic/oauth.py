from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass

import aiohttp

from app.core.auth.refresh import RefreshError, classify_refresh_error, get_token_refresh_timeout_override
from app.core.clients.http import lease_http_session
from app.core.config.settings import get_settings
from app.core.types import JsonObject
from app.core.utils.request_id import get_request_id

# Claude Code's public OAuth client. The token endpoint and beta flag match
# what Claude Code itself sends; the refresh token is single-use and every
# successful exchange rotates it.
ANTHROPIC_OAUTH_CLIENT_ID = "9d1c250a-e61b-44d9-88ed-5944d1962f5e"
ANTHROPIC_TOKEN_URL = "https://api.anthropic.com/v1/oauth/token"
ANTHROPIC_OAUTH_BETA = "oauth-2025-04-20"

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ClaudeTokenRefreshResult:
    access_token: str
    refresh_token: str
    expires_at: int
    """Access-token expiry as epoch seconds."""
    scopes: tuple[str, ...] = ()
    subscription_type: str | None = None


async def refresh_claude_access_token(
    refresh_token: str,
    *,
    session: aiohttp.ClientSession | None = None,
) -> ClaudeTokenRefreshResult:
    settings = get_settings()
    payload = {
        "grant_type": "refresh_token",
        "refresh_token": refresh_token,
        "client_id": ANTHROPIC_OAUTH_CLIENT_ID,
    }
    headers = {
        "content-type": "application/json",
        "anthropic-beta": ANTHROPIC_OAUTH_BETA,
    }
    request_id = get_request_id()
    if request_id:
        headers["x-request-id"] = request_id
    timeout_seconds = settings.token_refresh_timeout_seconds
    override = get_token_refresh_timeout_override()
    if override is not None:
        timeout_seconds = max(0.001, min(timeout_seconds, override))
    timeout = aiohttp.ClientTimeout(total=timeout_seconds)

    try:
        async with lease_http_session(session) as client_session:
            async with client_session.post(
                ANTHROPIC_TOKEN_URL,
                json=payload,
                headers=headers,
                timeout=timeout,
            ) as resp:
                data = await _safe_json(resp)
                if resp.status >= 400:
                    logger.warning(
                        "Claude token refresh failed request_id=%s status=%s",
                        get_request_id(),
                        resp.status,
                    )
                    raise _refresh_error_from_payload(data, resp.status)
    except RefreshError:
        raise
    except (aiohttp.ClientError, asyncio.TimeoutError, OSError) as exc:
        message = str(exc) or exc.__class__.__name__
        raise RefreshError(
            "transport_error",
            f"Transport error during Claude token refresh: {message}",
            False,
            transport_error=True,
        ) from exc

    access_token = data.get("access_token")
    new_refresh_token = data.get("refresh_token")
    expires_in = data.get("expires_in")
    if not isinstance(access_token, str) or not access_token or not isinstance(new_refresh_token, str):
        raise RefreshError("invalid_response", "Claude refresh response missing tokens", False)
    if not isinstance(expires_in, int | float):
        raise RefreshError("invalid_response", "Claude refresh response missing expires_in", False)

    scope = data.get("scope")
    scopes = tuple(scope.split()) if isinstance(scope, str) else ()
    subscription_type = data.get("subscription_type")
    return ClaudeTokenRefreshResult(
        access_token=access_token,
        refresh_token=new_refresh_token,
        expires_at=int(time.time()) + int(expires_in),
        scopes=scopes,
        subscription_type=subscription_type if isinstance(subscription_type, str) else None,
    )


async def _safe_json(resp: aiohttp.ClientResponse) -> JsonObject:
    try:
        data = await resp.json(content_type=None)
    except Exception:
        text = await resp.text()
        return {"error": {"message": text.strip()}}
    return data if isinstance(data, dict) else {"error": {"message": str(data)}}


def _refresh_error_from_payload(data: JsonObject, status_code: int) -> RefreshError:
    code: str | None = None
    message: str | None = None
    error = data.get("error")
    if isinstance(error, dict):
        raw_code = error.get("type") or error.get("code") or error.get("error")
        code = raw_code if isinstance(raw_code, str) else None
        raw_message = error.get("message") or error.get("error_description")
        message = raw_message if isinstance(raw_message, str) else None
    elif isinstance(error, str):
        code = error
    if code is None:
        raw_code = data.get("error_code") or data.get("code")
        code = raw_code if isinstance(raw_code, str) else None
    if message is None:
        raw_message = data.get("error_description") or data.get("message")
        message = raw_message if isinstance(raw_message, str) else None
    # A dead/rotated-away refresh token normally surfaces as invalid_grant in
    # the body; normalize only a code-less 401 onto it so the shared
    # permanent-failure classification (-> REAUTH_REQUIRED) applies. Other
    # code-less statuses stay non-permanent: never kill an account on an
    # ambiguous response.
    if code is None and status_code == 401:
        code = "invalid_grant"
    code = code or f"http_{status_code}"
    message = message or f"Claude token refresh failed ({status_code})"
    return RefreshError(code, message, classify_refresh_error(code))

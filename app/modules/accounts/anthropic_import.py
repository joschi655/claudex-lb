"""Parse Claude Code / Anthropic credentials for account import.

Accepts the credential shapes an operator already has on disk:

* Claude Code OAuth backups — a JSON object with a ``claudeAiOauth`` block
  (``accessToken`` / ``refreshToken`` / ``expiresAt`` in milliseconds, plus
  optional ``scopes`` / ``subscriptionType``), optionally wrapped with an
  ``email`` field.
* Static console API keys — ``{"email": ..., "apiKey": "sk-ant-..."}`` — which
  are consumption-based, have no refresh token, and are routed last by default.
"""

from __future__ import annotations

import json
import uuid
from collections.abc import Mapping
from dataclasses import dataclass
from typing import cast

_STATIC_API_KEY_FIELDS = ("apiKey", "anthropicApiKey", "api_key")
_EMAIL_FIELDS = ("email", "emailAddress")

# Fallback address minted for payloads without an email. It carries no account
# identity: dedupe-by-email must never match on it.
SYNTHETIC_IMPORT_EMAIL_SUFFIX = "@imported.local"


class InvalidAnthropicCredentialError(ValueError):
    """Raised when a payload looks anthropic-shaped but is malformed."""


@dataclass(frozen=True)
class AnthropicImport:
    email: str
    access_token: str
    refresh_token: str | None
    """``None`` for static console credentials (never refreshed)."""
    access_token_expires_at: int | None
    """Epoch seconds; ``None`` when not tracked (static or absent)."""
    plan_type: str
    is_static: bool


def looks_like_anthropic_payload(data: object) -> bool:
    if not isinstance(data, dict):
        return False
    if "claudeAiOauth" in data:
        return True
    return any(field in data for field in _STATIC_API_KEY_FIELDS)


def parse_anthropic_credential(data: dict[str, object]) -> AnthropicImport:
    email = _extract_email(data)

    oauth = data.get("claudeAiOauth")
    if isinstance(oauth, Mapping):
        return _parse_oauth(cast("Mapping[str, object]", oauth), email=email)

    for field in _STATIC_API_KEY_FIELDS:
        value = data.get(field)
        if isinstance(value, str) and value.strip():
            return AnthropicImport(
                email=email,
                access_token=value.strip(),
                refresh_token=None,
                access_token_expires_at=None,
                plan_type="claude_console",
                is_static=True,
            )

    raise InvalidAnthropicCredentialError("Anthropic payload has no claudeAiOauth block or API key")


def parse_anthropic_credential_bytes(raw: bytes) -> AnthropicImport:
    try:
        data = json.loads(raw)
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise InvalidAnthropicCredentialError("Payload is not valid JSON") from exc
    if not isinstance(data, dict):
        raise InvalidAnthropicCredentialError("Payload is not a JSON object")
    return parse_anthropic_credential(data)


def _parse_oauth(oauth: Mapping[str, object], *, email: str) -> AnthropicImport:
    access_token = oauth.get("accessToken")
    if not isinstance(access_token, str) or not access_token:
        raise InvalidAnthropicCredentialError("claudeAiOauth is missing accessToken")

    refresh_token_raw = oauth.get("refreshToken")
    refresh_token = refresh_token_raw if isinstance(refresh_token_raw, str) and refresh_token_raw else None

    expires_at = _epoch_seconds_from_ms(oauth.get("expiresAt"))

    subscription = oauth.get("subscriptionType")
    plan_type = f"claude_{subscription}" if isinstance(subscription, str) and subscription else "claude"

    return AnthropicImport(
        email=email,
        access_token=access_token,
        refresh_token=refresh_token,
        access_token_expires_at=expires_at,
        plan_type=plan_type,
        # An OAuth block without a refresh token can never be refreshed; treat
        # it as static so it degrades on 401 instead of hammering a refresh.
        is_static=refresh_token is None,
    )


def _extract_email(data: dict[str, object]) -> str:
    for field in _EMAIL_FIELDS:
        value = data.get(field)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return f"anthropic-{uuid.uuid4().hex[:8]}{SYNTHETIC_IMPORT_EMAIL_SUFFIX}"


# Epoch values at or above this are milliseconds (~year 5138 in seconds); Claude
# Code writes ms, but tolerate a seconds-based payload from other tooling so an
# already-valid expiry is not misread as 1970 (which would force a needless
# refresh and burn the single-use refresh token).
_EPOCH_MS_THRESHOLD = 100_000_000_000


def _epoch_seconds_from_ms(value: object) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int | float):
        number = int(value)
        return number // 1000 if number >= _EPOCH_MS_THRESHOLD else number
    return None

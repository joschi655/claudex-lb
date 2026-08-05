"""Read an Anthropic account's quota state from Anthropic's own usage endpoint.

The relay learns quota state from the ``anthropic-ratelimit-unified-*`` headers on
responses it serves, which means an account the pool is not currently using cannot
tell the pool anything: its last sample stands as its state however old it is. This
module closes that gap by asking upstream directly.

Two payload shapes come back. A subscription seat reports ``five_hour`` and
``seven_day`` utilizations. A usage-based seat reports neither, and instead carries a
bucket of dollars -- a limit, an amount spent, and a remainder. The bucket arrives
under a rotating code word (``cinder_cove``, ``tangelo``, ``nimbus_quill``, ...), so it
is found by looking for the dollar fields rather than by name.

Note that ``utilization`` here is a percentage (``77.72`` means 77.72%), whereas the
response headers report the same quantity as a fraction. Nothing needs to guess which
convention a value follows -- this module only ever sees percentages.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

import aiohttp

from app.core.anthropic.oauth import ANTHROPIC_OAUTH_BETA
from app.core.anthropic.upstream import ANTHROPIC_API_BASE, credential_is_static_api_key, open_get

logger = logging.getLogger(__name__)

USAGE_URL = f"{ANTHROPIC_API_BASE}/api/oauth/usage"

_TIMEOUT_SECONDS = 20.0
# The payload is a few hundred bytes of quota figures. Anything substantially
# larger is not the document this parser understands.
_MAX_BODY_BYTES = 256 * 1024


@dataclass(frozen=True, slots=True)
class AnthropicUsageWindow:
    used_percent: float
    reset_at: int | None = None


@dataclass(frozen=True, slots=True)
class AnthropicSpendBudget:
    """A dollar-denominated quota bucket, as reported by a usage-based seat."""

    used_percent: float
    used_dollars: float | None = None
    limit_dollars: float | None = None
    remaining_dollars: float | None = None
    currency: str | None = None
    reset_at: int | None = None


@dataclass(frozen=True, slots=True)
class AnthropicExtraCredits:
    """Top-up credits that cover usage past the plan's own limits."""

    enabled: bool
    used_dollars: float | None = None
    limit_dollars: float | None = None
    currency: str | None = None


@dataclass(frozen=True, slots=True)
class AnthropicUsageApiSnapshot:
    primary: AnthropicUsageWindow | None = None
    secondary: AnthropicUsageWindow | None = None
    budget: AnthropicSpendBudget | None = None
    extra_credits: AnthropicExtraCredits | None = None

    @property
    def has_any(self) -> bool:
        return self.primary is not None or self.secondary is not None or self.budget is not None


class AnthropicUsageFetchError(Exception):
    """A usage poll that did not produce a snapshot."""

    def __init__(self, reason: str, *, status_code: int | None = None) -> None:
        super().__init__(reason)
        self.reason = reason
        self.status_code = status_code

    @property
    def throttled(self) -> bool:
        return self.status_code == 429

    @property
    def unauthorized(self) -> bool:
        return self.status_code in (401, 403)


async def fetch_anthropic_usage(credential: str) -> AnthropicUsageApiSnapshot:
    """Ask Anthropic for one account's quota state.

    Raises ``AnthropicUsageFetchError`` for every unsuccessful outcome so the
    caller can distinguish throttling (expected, back off) from an auth failure
    (worth surfacing) without inspecting HTTP details itself.
    """
    if credential_is_static_api_key(credential):
        raise AnthropicUsageFetchError("static_api_key_has_no_subscription_usage")

    response = None
    try:
        response = await open_get(
            USAGE_URL,
            headers={
                "Authorization": f"Bearer {credential}",
                "Content-Type": "application/json",
                "Accept": "application/json",
                "anthropic-beta": ANTHROPIC_OAUTH_BETA,
            },
            timeout_seconds=_TIMEOUT_SECONDS,
        )
        raw = await response.read()
        status = response.status
    except aiohttp.ClientError as exc:
        raise AnthropicUsageFetchError(f"upstream_unavailable: {exc}"[:200]) from exc
    except TimeoutError as exc:
        raise AnthropicUsageFetchError("timeout") from exc
    finally:
        if response is not None:
            await response.aclose()

    if status != 200:
        raise AnthropicUsageFetchError(f"http_{status}", status_code=status)
    payload = _decode(raw)
    if payload is None:
        raise AnthropicUsageFetchError("unparseable_payload", status_code=status)
    return parse_usage_payload(payload)


def parse_usage_payload(payload: Mapping[str, Any]) -> AnthropicUsageApiSnapshot:
    """Read a usage payload into a snapshot, tolerating every shape it may take.

    Deliberately total: an unrecognized or partial document yields an empty
    snapshot rather than an exception, so an upstream field rename degrades to
    "learned nothing this tick" instead of breaking the refresh loop.
    """
    return AnthropicUsageApiSnapshot(
        primary=_window(payload.get("five_hour")),
        secondary=_window(payload.get("seven_day")),
        budget=_budget(payload),
        extra_credits=_extra_credits(payload),
    )


def _window(raw: Any) -> AnthropicUsageWindow | None:
    if not isinstance(raw, Mapping):
        return None
    used_percent = _percent(raw.get("utilization"))
    if used_percent is None:
        return None
    return AnthropicUsageWindow(used_percent=used_percent, reset_at=_epoch(raw.get("resets_at")))


def _budget(payload: Mapping[str, Any]) -> AnthropicSpendBudget | None:
    """Find the dollar bucket by its contents rather than by its key.

    The payload reserves a slot per named quota bucket and renames them over
    time, so the only durable signal that a bucket denominates dollars is that it
    carries a ``limit_dollars``. ``five_hour``/``seven_day`` are excluded: on a
    subscription seat they are windows, not budgets.
    """
    for key, value in payload.items():
        if key in ("five_hour", "seven_day"):
            continue
        if not isinstance(value, Mapping):
            continue
        limit_dollars = _float(value.get("limit_dollars"))
        if limit_dollars is None:
            continue
        used_dollars = _float(value.get("used_dollars"))
        used_percent = _percent(value.get("utilization"))
        if used_percent is None and used_dollars is not None and limit_dollars:
            used_percent = (used_dollars / limit_dollars) * 100.0
        if used_percent is None:
            continue
        return AnthropicSpendBudget(
            used_percent=used_percent,
            used_dollars=used_dollars,
            limit_dollars=limit_dollars,
            remaining_dollars=_float(value.get("remaining_dollars")),
            currency=_currency(payload),
            reset_at=_epoch(value.get("resets_at")),
        )
    return None


def _extra_credits(payload: Mapping[str, Any]) -> AnthropicExtraCredits | None:
    """Top-up credits, read from ``spend`` and cross-checked against ``extra_usage``.

    ``spend`` states the amounts in minor units with an explicit exponent, which
    is the unambiguous source; ``extra_usage`` is consulted only for whether the
    facility is switched on at all.
    """
    extra_usage = payload.get("extra_usage")
    spend = payload.get("spend")
    enabled = False
    if isinstance(extra_usage, Mapping):
        enabled = bool(extra_usage.get("is_enabled"))
    if isinstance(spend, Mapping) and spend.get("enabled") is True:
        enabled = True
    if not isinstance(spend, Mapping):
        return AnthropicExtraCredits(enabled=enabled) if enabled else None
    used = _money(spend.get("used"))
    limit = _money(spend.get("limit"))
    if not enabled and used is None and limit is None:
        return None
    return AnthropicExtraCredits(
        enabled=enabled,
        used_dollars=used,
        limit_dollars=limit,
        currency=_money_currency(spend.get("used")) or _money_currency(spend.get("limit")),
    )


def _money(raw: Any) -> float | None:
    """A ``{amount_minor, exponent}`` amount as a major-unit float."""
    if not isinstance(raw, Mapping):
        return None
    amount_minor = _float(raw.get("amount_minor"))
    if amount_minor is None:
        return None
    exponent = raw.get("exponent")
    if not isinstance(exponent, int) or isinstance(exponent, bool) or exponent < 0 or exponent > 6:
        exponent = 2
    return amount_minor / (10**exponent)


def _money_currency(raw: Any) -> str | None:
    if not isinstance(raw, Mapping):
        return None
    currency = raw.get("currency")
    return currency if isinstance(currency, str) and currency else None


def _currency(payload: Mapping[str, Any]) -> str | None:
    extra_usage = payload.get("extra_usage")
    if isinstance(extra_usage, Mapping):
        currency = extra_usage.get("currency")
        if isinstance(currency, str) and currency:
            return currency
    spend = payload.get("spend")
    if isinstance(spend, Mapping):
        return _money_currency(spend.get("used")) or _money_currency(spend.get("limit"))
    return None


def _percent(raw: Any) -> float | None:
    value = _float(raw)
    if value is None or value < 0:
        return None
    return min(100.0, value)


def _float(raw: Any) -> float | None:
    if isinstance(raw, bool) or raw is None:
        return None
    if isinstance(raw, (int, float)):
        return float(raw)
    if isinstance(raw, str):
        try:
            return float(raw)
        except ValueError:
            return None
    return None


def _epoch(raw: Any) -> int | None:
    """``resets_at`` as epoch seconds, from either an ISO 8601 string or a number."""
    if isinstance(raw, bool):
        return None
    if isinstance(raw, (int, float)):
        return int(raw)
    if not isinstance(raw, str) or not raw.strip():
        return None
    text = raw.strip()
    if text.endswith("Z"):
        text = f"{text[:-1]}+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        # Upstream always sends an offset; if one ever goes missing, reading it as
        # UTC beats inheriting whatever timezone the host happens to run in.
        parsed = parsed.replace(tzinfo=timezone.utc)
    return int(parsed.timestamp())


def _decode(raw: bytes) -> dict[str, Any] | None:
    if not raw or len(raw) > _MAX_BODY_BYTES:
        return None
    try:
        parsed = json.loads(raw)
    except (ValueError, UnicodeDecodeError):
        return None
    return parsed if isinstance(parsed, dict) else None

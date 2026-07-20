"""Parse Anthropic unified rate-limit response headers into usage snapshots.

Messages API responses (including 429s) carry ``anthropic-ratelimit-unified-*``
headers describing the account's 5h and 7d window utilization. The parser is
deliberately permissive: any missing or malformed header yields ``None`` for
that field and never raises, so a header-shape change upstream degrades to "no
usage written" rather than a failed relay.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

_PRIMARY_UTILIZATION = "anthropic-ratelimit-unified-5h-utilization"
_PRIMARY_RESET = "anthropic-ratelimit-unified-5h-reset"
_SECONDARY_UTILIZATION = "anthropic-ratelimit-unified-7d-utilization"
_SECONDARY_RESET = "anthropic-ratelimit-unified-7d-reset"


@dataclass(frozen=True)
class AnthropicUsageSnapshot:
    primary_used_percent: float | None = None
    primary_reset_at: int | None = None
    secondary_used_percent: float | None = None
    secondary_reset_at: int | None = None

    @property
    def has_any(self) -> bool:
        return self.primary_used_percent is not None or self.secondary_used_percent is not None


def parse_unified_usage(headers: Mapping[str, str]) -> AnthropicUsageSnapshot:
    lowered = {key.lower(): value for key, value in headers.items()}
    return AnthropicUsageSnapshot(
        primary_used_percent=_utilization_percent(lowered.get(_PRIMARY_UTILIZATION)),
        primary_reset_at=_epoch(lowered.get(_PRIMARY_RESET)),
        secondary_used_percent=_utilization_percent(lowered.get(_SECONDARY_UTILIZATION)),
        secondary_reset_at=_epoch(lowered.get(_SECONDARY_RESET)),
    )


def _utilization_percent(raw: str | None) -> float | None:
    if raw is None:
        return None
    try:
        value = float(raw)
    except (TypeError, ValueError):
        return None
    if value < 0:
        return None
    # Anthropic reports utilization as a 0-1 fraction; tolerate an already-percent
    # value (0-100) too. Values at or below 1 are treated as a fraction.
    percent = value * 100 if value <= 1 else value
    return min(100.0, percent)


def _epoch(raw: str | None) -> int | None:
    if raw is None:
        return None
    try:
        return int(float(raw))
    except (TypeError, ValueError):
        return None

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
    """Read a unified rate-limit utilization header as a percentage.

    The header is a fraction of the window, and it does not stop at 1: an account
    that has gone over reports ``1.04`` for 104%. Treating a value above 1 as an
    "already a percentage" figure -- the tolerance this parser used to carry --
    turns that into 1.04%, which is not merely wrong but inverted. It says the
    window is empty at the exact moment it is spent.

    That misreading is self-sustaining, because a 429 carries these headers too.
    Observed live: an account hit its five-hour limit, its own 429 rewrote the
    stored window to 1.04% used, the balancer read that as a fresh account and
    routed to it again, and the next 429 wrote 1.04% once more.

    The tolerance is gone rather than widened. There is no value in ``(1, 100]``
    that can be told apart from a fraction by inspection, and the fraction is the
    contract. A format change upstream is now recoverable in a way it was not
    when this parser was written: the usage poll reads the same two windows from
    ``/api/oauth/usage`` on its own percentage scale, so every account is
    corrected within a poll cycle instead of relying on a guess here.
    """
    if raw is None:
        return None
    try:
        value = float(raw)
    except (TypeError, ValueError):
        return None
    if value < 0:
        return None
    return min(100.0, value * 100)


def _epoch(raw: str | None) -> int | None:
    if raw is None:
        return None
    try:
        return int(float(raw))
    except (TypeError, ValueError):
        return None

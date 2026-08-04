"""Parse standard Anthropic API rate-limit response headers."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime, timezone
from math import isfinite

_LIMIT_GROUPS = ("requests", "tokens", "input-tokens", "output-tokens")


@dataclass(frozen=True, slots=True)
class AnthropicRateLimit:
    quota_key: str
    limit_name: str
    used_percent: float
    reset_at: int | None


def parse_rate_limits(headers: Mapping[str, str]) -> tuple[AnthropicRateLimit, ...]:
    lowered = {key.lower(): value for key, value in headers.items()}
    snapshots: list[AnthropicRateLimit] = []
    for group in _LIMIT_GROUPS:
        prefix = f"anthropic-ratelimit-{group}"
        limit = _non_negative_float(lowered.get(f"{prefix}-limit"))
        remaining = _non_negative_float(lowered.get(f"{prefix}-remaining"))
        if limit is None or remaining is None or limit <= 0:
            continue
        used_percent = round(
            max(0.0, min(100.0, ((limit - min(limit, remaining)) / limit) * 100.0)),
            6,
        )
        snapshots.append(
            AnthropicRateLimit(
                quota_key=f"anthropic_{group.replace('-', '_')}",
                limit_name=f"Anthropic {group.replace('-', ' ').title()}",
                used_percent=used_percent,
                reset_at=parse_reset_at(lowered.get(f"{prefix}-reset")),
            )
        )
    return tuple(snapshots)


def parse_reset_at(raw: str | None) -> int | None:
    if raw is None:
        return None
    value = raw.strip()
    if not value:
        return None
    try:
        numeric = float(value)
    except ValueError:
        numeric = None
    if numeric is not None:
        if not isfinite(numeric):
            return None
        return int(numeric)
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return int(parsed.timestamp())


def _non_negative_float(raw: str | None) -> float | None:
    if raw is None:
        return None
    try:
        value = float(raw)
    except (TypeError, ValueError):
        return None
    return value if isfinite(value) and value >= 0 else None

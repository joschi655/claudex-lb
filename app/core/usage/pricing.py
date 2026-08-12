from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from fnmatch import fnmatchcase
from typing import Iterable, Mapping

from app.core.openai.models import ResponseUsage
from app.core.usage.types import UsageCostByModel, UsageCostSummary


@dataclass(frozen=True)
class ModelPrice:
    input_per_1m: float
    output_per_1m: float
    cached_input_per_1m: float | None = None
    # Prompt-cache writes, which cost *more* than uncached input rather than
    # less (Anthropic charges 1.25x base for a 5-minute entry). Left unset by
    # models that do not bill writes separately, in which case write tokens are
    # charged at the base input rate exactly as they were before this existed.
    cache_write_per_1m: float | None = None
    priority_multiplier: float | None = None
    priority_input_per_1m: float | None = None
    priority_output_per_1m: float | None = None
    priority_cached_input_per_1m: float | None = None
    flex_input_per_1m: float | None = None
    flex_output_per_1m: float | None = None
    flex_cached_input_per_1m: float | None = None
    long_context_threshold_tokens: float | None = None
    long_context_input_per_1m: float | None = None
    long_context_output_per_1m: float | None = None
    long_context_cached_input_per_1m: float | None = None


@dataclass(frozen=True)
class UsageTokens:
    """Input split into three disjoint parts, plus output.

    ``input_tokens`` is the total prompt size; the two cache counters are
    subsets of it, and what remains after both is the uncached input. Keeping
    the total rather than the uncached part is what lets a stored row from
    before the cache-write counter existed still be priced.
    """

    input_tokens: float
    output_tokens: float
    cached_input_tokens: float = 0.0
    cache_write_input_tokens: float = 0.0


@dataclass(frozen=True)
class UsageCostBreakdown:
    input_usd: float | None
    cached_input_usd: float | None
    output_usd: float | None
    total_usd: float | None
    cache_write_usd: float | None = None


@dataclass(frozen=True)
class CostItem:
    model: str
    usage: UsageTokens
    service_tier: str | None = None


def _as_number(value: int | float | None) -> float | None:
    if isinstance(value, (int, float)):
        return float(value)
    return None


def _clamp_cache_parts(
    input_tokens: float,
    cached_tokens: float,
    cache_write_tokens: float,
) -> tuple[float, float]:
    """Keep the two cache counters inside the total they are subsets of.

    They are charged at different rates, so a row whose parts exceed its total —
    a truncated count, a hand-written test fixture — must not be able to bill
    more input than the request had. Cache reads are trusted first because they
    are the cheaper rate: clamping the writes instead would let a bad row cost
    more, not less.
    """
    cached = max(0.0, min(cached_tokens, input_tokens))
    write = max(0.0, min(cache_write_tokens, input_tokens - cached))
    return cached, write


def _normalize_usage(usage: UsageTokens | ResponseUsage | None) -> UsageTokens | None:
    if isinstance(usage, UsageTokens):
        input_tokens = _as_number(usage.input_tokens)
        output_tokens = _as_number(usage.output_tokens)
        cached_tokens = _as_number(usage.cached_input_tokens)
        cache_write_tokens = _as_number(usage.cache_write_input_tokens)
        if input_tokens is None or output_tokens is None:
            return None
        cached_tokens, cache_write_tokens = _clamp_cache_parts(
            input_tokens,
            cached_tokens or 0.0,
            cache_write_tokens or 0.0,
        )
        return UsageTokens(
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cached_input_tokens=cached_tokens,
            cache_write_input_tokens=cache_write_tokens,
        )
    if not usage:
        return None
    input_tokens = _as_number(usage.input_tokens)
    output_tokens = _as_number(usage.output_tokens)
    if output_tokens is None and usage.output_tokens_details is not None:
        output_tokens = _as_number(usage.output_tokens_details.reasoning_tokens)
    if input_tokens is None or output_tokens is None:
        return None
    cached_tokens = 0.0
    if usage.input_tokens_details is not None:
        cached_tokens = _as_number(usage.input_tokens_details.cached_tokens) or 0.0
    cached_tokens = max(0.0, min(cached_tokens, input_tokens))
    return UsageTokens(
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        cached_input_tokens=cached_tokens,
    )


DEFAULT_PRICING_MODELS: dict[str, ModelPrice] = {
    "gpt-5.5": ModelPrice(
        input_per_1m=5.0,
        cached_input_per_1m=0.5,
        output_per_1m=30.0,
        flex_input_per_1m=2.5,
        flex_cached_input_per_1m=0.25,
        flex_output_per_1m=15.0,
        priority_input_per_1m=12.5,
        priority_cached_input_per_1m=1.25,
        priority_output_per_1m=75.0,
    ),
    "gpt-5.5-pro": ModelPrice(
        input_per_1m=30.0,
        output_per_1m=180.0,
        flex_input_per_1m=15.0,
        flex_output_per_1m=90.0,
    ),
    "gpt-5.4": ModelPrice(
        input_per_1m=2.5,
        cached_input_per_1m=0.25,
        output_per_1m=15.0,
        priority_input_per_1m=5.0,
        priority_cached_input_per_1m=0.5,
        priority_output_per_1m=30.0,
        flex_input_per_1m=1.25,
        flex_cached_input_per_1m=0.125,
        flex_output_per_1m=7.5,
        long_context_threshold_tokens=272_000,
        long_context_input_per_1m=5.0,
        long_context_cached_input_per_1m=0.5,
        long_context_output_per_1m=22.5,
    ),
    "gpt-5.4-mini": ModelPrice(
        input_per_1m=0.75,
        cached_input_per_1m=0.075,
        output_per_1m=4.5,
        flex_input_per_1m=0.375,
        flex_cached_input_per_1m=0.0375,
        flex_output_per_1m=2.25,
    ),
    "gpt-5.4-nano": ModelPrice(
        input_per_1m=0.20,
        cached_input_per_1m=0.02,
        output_per_1m=1.25,
        flex_input_per_1m=0.10,
        flex_cached_input_per_1m=0.01,
        flex_output_per_1m=0.625,
    ),
    "gpt-5.4-pro": ModelPrice(
        input_per_1m=30.0,
        output_per_1m=180.0,
        flex_input_per_1m=15.0,
        flex_output_per_1m=90.0,
        long_context_threshold_tokens=272_000,
        long_context_input_per_1m=60.0,
        long_context_output_per_1m=270.0,
    ),
    "gpt-5.3-codex": ModelPrice(
        input_per_1m=1.75,
        cached_input_per_1m=0.175,
        output_per_1m=14.0,
        priority_input_per_1m=3.5,
        priority_cached_input_per_1m=0.35,
        priority_output_per_1m=28.0,
    ),
    "gpt-5.3": ModelPrice(
        input_per_1m=1.75,
        cached_input_per_1m=0.175,
        output_per_1m=14.0,
    ),
    "gpt-5.3-chat-latest": ModelPrice(
        input_per_1m=1.75,
        cached_input_per_1m=0.175,
        output_per_1m=14.0,
    ),
    "gpt-5.2": ModelPrice(
        input_per_1m=1.75,
        cached_input_per_1m=0.175,
        output_per_1m=14.0,
        priority_multiplier=2.0,
        flex_input_per_1m=0.875,
        flex_cached_input_per_1m=0.0875,
        flex_output_per_1m=7.0,
    ),
    "gpt-5.2-chat-latest": ModelPrice(
        input_per_1m=1.75,
        cached_input_per_1m=0.175,
        output_per_1m=14.0,
    ),
    "gpt-5.1": ModelPrice(
        input_per_1m=1.25,
        cached_input_per_1m=0.125,
        output_per_1m=10.0,
        priority_multiplier=2.0,
        flex_input_per_1m=0.625,
        flex_cached_input_per_1m=0.0625,
        flex_output_per_1m=5.0,
    ),
    "gpt-5.1-chat-latest": ModelPrice(
        input_per_1m=1.25,
        cached_input_per_1m=0.125,
        output_per_1m=10.0,
    ),
    "gpt-5": ModelPrice(
        input_per_1m=1.25,
        cached_input_per_1m=0.125,
        output_per_1m=10.0,
        priority_multiplier=2.0,
        flex_input_per_1m=0.625,
        flex_cached_input_per_1m=0.0625,
        flex_output_per_1m=5.0,
    ),
    "gpt-5-chat-latest": ModelPrice(
        input_per_1m=1.25,
        cached_input_per_1m=0.125,
        output_per_1m=10.0,
    ),
    "gpt-5.2-codex": ModelPrice(
        input_per_1m=1.75,
        cached_input_per_1m=0.175,
        output_per_1m=14.0,
        priority_input_per_1m=3.5,
        priority_cached_input_per_1m=0.35,
        priority_output_per_1m=28.0,
    ),
    "gpt-5.1-codex-max": ModelPrice(
        input_per_1m=1.25,
        cached_input_per_1m=0.125,
        output_per_1m=10.0,
        priority_input_per_1m=2.5,
        priority_cached_input_per_1m=0.25,
        priority_output_per_1m=20.0,
    ),
    "gpt-5.1-codex-mini": ModelPrice(
        input_per_1m=0.25,
        cached_input_per_1m=0.025,
        output_per_1m=2.0,
    ),
    "gpt-5.1-codex": ModelPrice(
        input_per_1m=1.25,
        cached_input_per_1m=0.125,
        output_per_1m=10.0,
        priority_input_per_1m=2.5,
        priority_cached_input_per_1m=0.25,
        priority_output_per_1m=20.0,
    ),
    "gpt-5-codex": ModelPrice(
        input_per_1m=1.25,
        cached_input_per_1m=0.125,
        output_per_1m=10.0,
        priority_input_per_1m=2.5,
        priority_cached_input_per_1m=0.25,
        priority_output_per_1m=20.0,
    ),
    # OpenAI Images token-based pricing (per 1M tokens, USD).
    # gpt-image-2 (April 2026):
    #   text input  $5.00, image input $8.00, image cached input $2.00,
    #   image output $30.00.
    # The current ``ModelPrice`` shape carries a single input rate, so we
    # use the text-input rate as the dominant input cost (text dominates
    # the input side for typical prompts) and the image-output rate as
    # the output cost. Cached input maps to the image-cached rate.
    # The legacy gpt-image-1.5 / gpt-image-1 / gpt-image-1-mini entries
    # mirror gpt-image-2 today; they will be split out once OpenAI
    # publishes per-model deltas. Without these entries cost-based API
    # key quotas would resolve every /v1/images/* call to $0 and the
    # quota would never bite.
    "gpt-image-2": ModelPrice(
        input_per_1m=5.0,
        cached_input_per_1m=2.0,
        output_per_1m=30.0,
    ),
    "gpt-image-1.5": ModelPrice(
        input_per_1m=5.0,
        cached_input_per_1m=2.0,
        output_per_1m=30.0,
    ),
    "gpt-image-1": ModelPrice(
        input_per_1m=5.0,
        cached_input_per_1m=2.0,
        output_per_1m=30.0,
    ),
    "gpt-image-1-mini": ModelPrice(
        input_per_1m=5.0,
        cached_input_per_1m=2.0,
        output_per_1m=30.0,
    ),
    # Anthropic published rates, read from the model pricing table on
    # 2026-08-12. Cache reads are 0.1x base input and 5-minute cache writes are
    # 1.25x, which is what the published per-model columns work out to.
    #
    # No long-context threshold: Claude 4.6 and later carry the full 1M-token
    # window at standard pricing, so unlike gpt-5.4 there is no premium above a
    # cutoff. Adding one would invent a charge that does not exist.
    "claude-fable-5": ModelPrice(
        input_per_1m=10.0,
        cached_input_per_1m=1.0,
        cache_write_per_1m=12.5,
        output_per_1m=50.0,
    ),
    "claude-opus-5": ModelPrice(
        input_per_1m=5.0,
        cached_input_per_1m=0.5,
        cache_write_per_1m=6.25,
        output_per_1m=25.0,
    ),
    "claude-opus-4-8": ModelPrice(
        input_per_1m=5.0,
        cached_input_per_1m=0.5,
        cache_write_per_1m=6.25,
        output_per_1m=25.0,
    ),
    "claude-opus-4-7": ModelPrice(
        input_per_1m=5.0,
        cached_input_per_1m=0.5,
        cache_write_per_1m=6.25,
        output_per_1m=25.0,
    ),
    "claude-opus-4-6": ModelPrice(
        input_per_1m=5.0,
        cached_input_per_1m=0.5,
        cache_write_per_1m=6.25,
        output_per_1m=25.0,
    ),
    "claude-opus-4-5": ModelPrice(
        input_per_1m=5.0,
        cached_input_per_1m=0.5,
        cache_write_per_1m=6.25,
        output_per_1m=25.0,
    ),
    # $2/$10 is the standard price, not an introductory one: the increase to
    # $3/$15 scheduled for 2026-09-01 was cancelled.
    "claude-sonnet-5": ModelPrice(
        input_per_1m=2.0,
        cached_input_per_1m=0.2,
        cache_write_per_1m=2.5,
        output_per_1m=10.0,
    ),
    "claude-sonnet-4-6": ModelPrice(
        input_per_1m=3.0,
        cached_input_per_1m=0.3,
        cache_write_per_1m=3.75,
        output_per_1m=15.0,
    ),
    "claude-sonnet-4-5": ModelPrice(
        input_per_1m=3.0,
        cached_input_per_1m=0.3,
        cache_write_per_1m=3.75,
        output_per_1m=15.0,
    ),
    "claude-haiku-4-5": ModelPrice(
        input_per_1m=1.0,
        cached_input_per_1m=0.1,
        cache_write_per_1m=1.25,
        output_per_1m=5.0,
    ),
}

DEFAULT_MODEL_ALIASES: dict[str, str] = {
    "gpt-5.5-pro*": "gpt-5.5-pro",
    "gpt-5.5*": "gpt-5.5",
    "gpt-5.4-pro*": "gpt-5.4-pro",
    "gpt-5.4-mini*": "gpt-5.4-mini",
    "gpt-5.4-nano*": "gpt-5.4-nano",
    "gpt-5.4*": "gpt-5.4",
    "gpt-5.3-codex*": "gpt-5.3-codex",
    "gpt-5.3-chat-latest*": "gpt-5.3-chat-latest",
    "gpt-5.2-codex*": "gpt-5.2-codex",
    "gpt-5.2-chat-latest*": "gpt-5.2-chat-latest",
    "gpt-5.3*": "gpt-5.3",
    "gpt-5.1-chat-latest*": "gpt-5.1-chat-latest",
    "gpt-5.2*": "gpt-5.2",
    "gpt-5-chat-latest*": "gpt-5-chat-latest",
    "gpt-5.1*": "gpt-5.1",
    "gpt-5*": "gpt-5",
    "gpt-5.1-codex-max*": "gpt-5.1-codex-max",
    "gpt-5.1-codex-mini*": "gpt-5.1-codex-mini",
    "gpt-5.1-codex*": "gpt-5.1-codex",
    "gpt-5-codex*": "gpt-5-codex",
    "gpt-image-2*": "gpt-image-2",
    "gpt-image-1.5*": "gpt-image-1.5",
    "gpt-image-1-mini*": "gpt-image-1-mini",
    "gpt-image-1*": "gpt-image-1",
    # Claude identifiers arrive both bare (`claude-opus-5`) and snapshot-dated
    # (`claude-haiku-4-5-20251001`); both forms appear in real relay traffic.
    # resolve_model_alias takes the longest matching pattern, so the point
    # releases win over nothing broader — there is deliberately no
    # `claude-opus-4*` catch-all, which would swallow a future 4.9 at 4.8 rates.
    "claude-fable-5*": "claude-fable-5",
    "claude-opus-5*": "claude-opus-5",
    "claude-opus-4-8*": "claude-opus-4-8",
    "claude-opus-4-7*": "claude-opus-4-7",
    "claude-opus-4-6*": "claude-opus-4-6",
    "claude-opus-4-5*": "claude-opus-4-5",
    "claude-sonnet-5*": "claude-sonnet-5",
    "claude-sonnet-4-6*": "claude-sonnet-4-6",
    "claude-sonnet-4-5*": "claude-sonnet-4-5",
    "claude-haiku-4-5*": "claude-haiku-4-5",
}


def resolve_model_alias(model: str, aliases: Mapping[str, str]) -> str | None:
    if not model:
        return None
    normalized = model.lower()
    matched: list[tuple[int, str]] = []
    for pattern, target in aliases.items():
        if fnmatchcase(normalized, pattern.lower()):
            matched.append((len(pattern), target))
    if not matched:
        return None
    return max(matched, key=lambda item: item[0])[1]


def get_pricing_for_model(
    model: str,
    pricing: Mapping[str, ModelPrice] | None = None,
    aliases: Mapping[str, str] | None = None,
) -> tuple[str, ModelPrice] | None:
    if not model:
        return None
    pricing = pricing or DEFAULT_PRICING_MODELS
    aliases = aliases or DEFAULT_MODEL_ALIASES

    normalized = model.lower()
    for key, value in pricing.items():
        if key.lower() == normalized:
            return key, value

    alias = resolve_model_alias(normalized, aliases)
    if not alias:
        return None
    for key, value in pricing.items():
        if key.lower() == alias.lower():
            return key, value
    return None


def _uses_priority_tier(service_tier: str | None) -> bool:
    normalized = _normalize_service_tier(service_tier)
    if normalized is None:
        return False
    return normalized in {"priority", "fast"}


def _uses_flex_tier(service_tier: str | None) -> bool:
    normalized = _normalize_service_tier(service_tier)
    if normalized is None:
        return False
    return normalized == "flex"


def _normalize_service_tier(service_tier: str | None) -> str | None:
    if service_tier is None:
        return None
    stripped = service_tier.strip().lower()
    return stripped or None


def _effective_rates(
    usage: UsageTokens,
    price: ModelPrice,
    *,
    service_tier: str | None,
) -> tuple[float, float, float, float]:
    """Resolve the four rates a request is charged at, in USD per 1M tokens.

    Returned as (uncached input, cache read, cache write, output). The
    cache-write rate is the model's own when it states one, and otherwise the
    input rate that applies after tier and long-context adjustment — so a model
    that does not bill writes separately is charged exactly as it was before
    the rate existed, on every tier.
    """
    input_rate, cached_rate, output_rate = _effective_input_output_rates(
        usage,
        price,
        service_tier=service_tier,
    )
    # No model currently states both a cache-write rate and a non-standard
    # tier rate, so there is nothing to reconcile between them yet.
    cache_write_rate = price.cache_write_per_1m if price.cache_write_per_1m is not None else input_rate
    return input_rate, cached_rate, cache_write_rate, output_rate


def _effective_input_output_rates(
    usage: UsageTokens,
    price: ModelPrice,
    *,
    service_tier: str | None,
) -> tuple[float, float, float]:
    is_long_context = (
        price.long_context_threshold_tokens is not None
        and usage.input_tokens > price.long_context_threshold_tokens
        and price.long_context_input_per_1m is not None
        and price.long_context_output_per_1m is not None
    )
    input_rate = price.input_per_1m
    cached_rate = price.cached_input_per_1m if price.cached_input_per_1m is not None else input_rate
    output_rate = price.output_per_1m

    if _uses_priority_tier(service_tier):
        if price.priority_input_per_1m is not None and price.priority_output_per_1m is not None:
            priority_cached = (
                price.priority_cached_input_per_1m
                if price.priority_cached_input_per_1m is not None
                else price.priority_input_per_1m
            )
            return price.priority_input_per_1m, priority_cached, price.priority_output_per_1m
        if price.priority_multiplier is not None:
            input_rate *= price.priority_multiplier
            cached_rate *= price.priority_multiplier
            output_rate *= price.priority_multiplier
            return input_rate, cached_rate, output_rate

    if _uses_flex_tier(service_tier) and price.flex_input_per_1m is not None and price.flex_output_per_1m is not None:
        input_rate = price.flex_input_per_1m
        cached_rate = price.flex_cached_input_per_1m if price.flex_cached_input_per_1m is not None else input_rate
        output_rate = price.flex_output_per_1m
        if is_long_context:
            input_rate *= 2.0
            cached_rate *= 2.0
            output_rate *= 1.5
        return input_rate, cached_rate, output_rate

    if is_long_context:
        assert price.long_context_input_per_1m is not None
        assert price.long_context_output_per_1m is not None
        input_rate = price.long_context_input_per_1m
        cached_rate = (
            price.long_context_cached_input_per_1m if price.long_context_cached_input_per_1m is not None else input_rate
        )
        output_rate = price.long_context_output_per_1m

    return input_rate, cached_rate, output_rate


def calculate_cost_from_usage(
    usage: UsageTokens | ResponseUsage | None,
    price: ModelPrice,
    *,
    service_tier: str | None = None,
) -> float | None:
    breakdown = calculate_cost_breakdown_from_usage(usage, price, service_tier=service_tier)
    if breakdown is None:
        return None
    return breakdown.total_usd


def calculate_cost_breakdown_from_usage(
    usage: UsageTokens | ResponseUsage | None,
    price: ModelPrice,
    *,
    service_tier: str | None = None,
    precision: int | None = None,
) -> UsageCostBreakdown | None:
    normalized = _normalize_usage(usage)
    if not normalized:
        return None
    # The three input parts are disjoint and each is charged once: what is left
    # after both cache counters is the uncached input.
    billable_input = max(
        0.0,
        normalized.input_tokens - normalized.cached_input_tokens - normalized.cache_write_input_tokens,
    )

    input_rate, cached_rate, cache_write_rate, output_rate = _effective_rates(
        normalized,
        price,
        service_tier=service_tier,
    )

    input_usd = (billable_input / 1_000_000) * input_rate
    cached_input_usd = (normalized.cached_input_tokens / 1_000_000) * cached_rate
    cache_write_usd = (normalized.cache_write_input_tokens / 1_000_000) * cache_write_rate
    output_usd = (normalized.output_tokens / 1_000_000) * output_rate

    if precision is not None:
        input_usd = round(input_usd, precision)
        cached_input_usd = round(cached_input_usd, precision)
        cache_write_usd = round(cache_write_usd, precision)
        output_usd = round(output_usd, precision)

    total_usd = input_usd + cached_input_usd + cache_write_usd + output_usd

    if precision is not None:
        total_usd = round(total_usd, precision)

    return UsageCostBreakdown(
        input_usd=input_usd,
        cached_input_usd=cached_input_usd,
        cache_write_usd=cache_write_usd,
        output_usd=output_usd,
        total_usd=total_usd,
    )


def calculate_costs(
    items: Iterable[CostItem],
    pricing: Mapping[str, ModelPrice] | None = None,
    aliases: Mapping[str, str] | None = None,
) -> UsageCostSummary:
    pricing = pricing or DEFAULT_PRICING_MODELS
    aliases = aliases or DEFAULT_MODEL_ALIASES

    totals: dict[str, float] = defaultdict(float)
    total_usd = 0.0

    for item in items:
        model = item.model
        usage = item.usage
        resolved = get_pricing_for_model(model, pricing, aliases)
        if not resolved:
            continue
        canonical, price = resolved
        cost = calculate_cost_from_usage(usage, price, service_tier=item.service_tier)
        if cost is None:
            continue
        totals[canonical] += cost
        total_usd += cost

    by_model = [UsageCostByModel(model=model, usd=round(value, 6)) for model, value in sorted(totals.items())]
    return UsageCostSummary(
        currency="USD",
        total_usd_7d=round(total_usd, 6),
        by_model=by_model,
    )

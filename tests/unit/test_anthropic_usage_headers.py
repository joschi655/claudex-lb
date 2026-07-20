from __future__ import annotations

from app.core.anthropic.usage_headers import parse_unified_usage

pytestmark_names = ("unit",)


def test_parses_fraction_utilization_and_reset():
    snapshot = parse_unified_usage(
        {
            "anthropic-ratelimit-unified-5h-utilization": "0.42",
            "anthropic-ratelimit-unified-5h-reset": "1900000000",
            "anthropic-ratelimit-unified-7d-utilization": "0.10",
            "anthropic-ratelimit-unified-7d-reset": "1900500000",
        }
    )
    assert snapshot.primary_used_percent == 42.0
    assert snapshot.primary_reset_at == 1_900_000_000
    assert snapshot.secondary_used_percent == 10.0
    assert snapshot.secondary_reset_at == 1_900_500_000
    assert snapshot.has_any


def test_accepts_already_percent_values():
    snapshot = parse_unified_usage({"anthropic-ratelimit-unified-5h-utilization": "73"})
    assert snapshot.primary_used_percent == 73.0


def test_case_insensitive_headers():
    snapshot = parse_unified_usage({"Anthropic-RateLimit-Unified-5h-Utilization": "0.5"})
    assert snapshot.primary_used_percent == 50.0


def test_missing_headers_yield_empty_snapshot():
    snapshot = parse_unified_usage({"content-type": "text/event-stream"})
    assert not snapshot.has_any
    assert snapshot.primary_used_percent is None


def test_malformed_values_are_ignored():
    snapshot = parse_unified_usage(
        {
            "anthropic-ratelimit-unified-5h-utilization": "not-a-number",
            "anthropic-ratelimit-unified-5h-reset": "bogus",
        }
    )
    assert snapshot.primary_used_percent is None
    assert snapshot.primary_reset_at is None


def test_utilization_capped_at_100():
    snapshot = parse_unified_usage({"anthropic-ratelimit-unified-5h-utilization": "150"})
    assert snapshot.primary_used_percent == 100.0

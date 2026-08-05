"""The usage-API parser, exercised against the payload shapes upstream really sends."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from app.core.anthropic.usage_api import (
    AnthropicUsageFetchError,
    parse_usage_payload,
)

# Captured from a live Claude Pro seat on 2026-08-05, trimmed to the fields the
# parser reads plus enough of the null slots to prove they are ignored.
SUBSCRIPTION_PAYLOAD = {
    "five_hour": {
        "utilization": 100.0,
        "resets_at": "2026-08-05T12:50:00.124511+00:00",
        "limit_dollars": None,
        "used_dollars": None,
        "remaining_dollars": None,
    },
    "seven_day": {
        "utilization": 57.0,
        "resets_at": "2026-08-06T10:00:00.124537+00:00",
        "limit_dollars": None,
        "used_dollars": None,
        "remaining_dollars": None,
    },
    "seven_day_opus": None,
    "tangelo": None,
    "cinder_cove": None,
    "extra_usage": {"is_enabled": False, "monthly_limit": None, "used_credits": None},
    "limits": [{"kind": "session", "percent": 100, "severity": "critical"}],
    "spend": {
        "used": {"amount_minor": 0, "currency": "USD", "exponent": 2},
        "limit": None,
        "percent": 0,
        "enabled": False,
    },
}

# Captured from a live usage-based enterprise seat the same day. No windows at
# all -- the quota is the dollar bucket, and it arrives under a code word.
BUDGET_PAYLOAD = {
    "five_hour": None,
    "seven_day": None,
    "cinder_cove": {
        "utilization": 77.72440259999999,
        "resets_at": "2026-09-30T20:47:10.939005+00:00",
        "limit_dollars": 1000,
        "used_dollars": 777.244026,
        "remaining_dollars": 222.75597400000004,
    },
    "extra_usage": {
        "is_enabled": True,
        "monthly_limit": 20000,
        "used_credits": 1603.0,
        "utilization": 8.015,
        "currency": "USD",
        "decimal_places": 2,
    },
    "limits": [],
    "spend": {
        "used": {"amount_minor": 1603, "currency": "USD", "exponent": 2},
        "limit": {"amount_minor": 20000, "currency": "USD", "exponent": 2},
        "percent": 8,
        "enabled": True,
    },
}


def _epoch(text: str) -> int:
    return int(datetime.fromisoformat(text).timestamp())


def test_subscription_payload_yields_both_windows_and_no_budget():
    snapshot = parse_usage_payload(SUBSCRIPTION_PAYLOAD)

    assert snapshot.primary is not None
    assert snapshot.primary.used_percent == 100.0
    assert snapshot.primary.reset_at == _epoch("2026-08-05T12:50:00.124511+00:00")
    assert snapshot.secondary is not None
    assert snapshot.secondary.used_percent == 57.0
    assert snapshot.budget is None
    assert snapshot.has_any


def test_budget_payload_yields_the_dollar_bucket_and_no_windows():
    snapshot = parse_usage_payload(BUDGET_PAYLOAD)

    assert snapshot.primary is None
    assert snapshot.secondary is None
    assert snapshot.budget is not None
    assert snapshot.budget.used_percent == pytest.approx(77.7244026)
    assert snapshot.budget.limit_dollars == 1000.0
    assert snapshot.budget.used_dollars == pytest.approx(777.244026)
    assert snapshot.budget.remaining_dollars == pytest.approx(222.755974)
    assert snapshot.budget.currency == "USD"
    assert snapshot.budget.reset_at == _epoch("2026-09-30T20:47:10.939005+00:00")
    assert snapshot.has_any


def test_budget_is_found_under_a_key_the_code_has_never_seen():
    """Bucket names rotate upstream, so recognition must not depend on the name."""
    payload = {
        "five_hour": None,
        "seven_day": None,
        "brand_new_codeword": {
            "utilization": 12.5,
            "resets_at": "2026-12-01T00:00:00+00:00",
            "limit_dollars": 400,
            "used_dollars": 50,
            "remaining_dollars": 350,
        },
    }

    snapshot = parse_usage_payload(payload)

    assert snapshot.budget is not None
    assert snapshot.budget.limit_dollars == 400.0
    assert snapshot.budget.used_percent == 12.5


def test_a_window_is_never_mistaken_for_a_budget():
    """A subscription window with dollar fields set must still be a window."""
    payload = {
        "five_hour": {"utilization": 40.0, "resets_at": None, "limit_dollars": 99},
        "seven_day": None,
    }

    snapshot = parse_usage_payload(payload)

    assert snapshot.primary is not None
    assert snapshot.primary.used_percent == 40.0
    assert snapshot.budget is None


def test_utilization_is_read_as_a_percentage_not_a_fraction():
    """The API reports percentages even when they look like fractions.

    The response *headers* use fractions and the header parser has a heuristic
    for that; this endpoint does not, so a reported 1.0 means one percent.
    """
    snapshot = parse_usage_payload({"five_hour": {"utilization": 1.0, "resets_at": None}})

    assert snapshot.primary is not None
    assert snapshot.primary.used_percent == 1.0


def test_utilization_above_one_hundred_is_clamped():
    snapshot = parse_usage_payload({"five_hour": {"utilization": 137.0}})

    assert snapshot.primary is not None
    assert snapshot.primary.used_percent == 100.0


def test_all_null_payload_yields_nothing():
    snapshot = parse_usage_payload({"five_hour": None, "seven_day": None, "spend": None})

    assert snapshot.primary is None
    assert snapshot.secondary is None
    assert snapshot.budget is None
    assert not snapshot.has_any


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"five_hour": "unexpected"},
        {"five_hour": {"utilization": "not a number"}},
        {"five_hour": {"utilization": -5}},
        {"five_hour": []},
    ],
)
def test_malformed_shapes_degrade_to_an_empty_snapshot(payload):
    """A field rename upstream must cost this tick's data, not the refresh loop."""
    snapshot = parse_usage_payload(payload)

    assert not snapshot.has_any


def test_reset_without_an_offset_is_read_as_utc():
    snapshot = parse_usage_payload({"five_hour": {"utilization": 5, "resets_at": "2026-08-05T12:50:00"}})

    assert snapshot.primary is not None
    assert snapshot.primary.reset_at == int(datetime(2026, 8, 5, 12, 50, tzinfo=timezone.utc).timestamp())


def test_reset_accepts_a_trailing_z():
    snapshot = parse_usage_payload({"five_hour": {"utilization": 5, "resets_at": "2026-08-05T12:50:00Z"}})

    assert snapshot.primary is not None
    assert snapshot.primary.reset_at == int(datetime(2026, 8, 5, 12, 50, tzinfo=timezone.utc).timestamp())


def test_extra_credits_report_minor_units_as_major():
    snapshot = parse_usage_payload(BUDGET_PAYLOAD)

    assert snapshot.extra_credits is not None
    assert snapshot.extra_credits.enabled is True
    assert snapshot.extra_credits.used_dollars == pytest.approx(16.03)
    assert snapshot.extra_credits.limit_dollars == pytest.approx(200.0)
    assert snapshot.extra_credits.currency == "USD"


def test_extra_credits_absent_when_the_facility_is_off():
    snapshot = parse_usage_payload(SUBSCRIPTION_PAYLOAD)

    assert snapshot.extra_credits is not None
    assert snapshot.extra_credits.enabled is False
    assert snapshot.extra_credits.used_dollars == 0.0


def test_budget_percentage_is_derived_when_upstream_omits_it():
    payload = {"a_bucket": {"limit_dollars": 200, "used_dollars": 50}}

    snapshot = parse_usage_payload(payload)

    assert snapshot.budget is not None
    assert snapshot.budget.used_percent == pytest.approx(25.0)


def test_fetch_error_classifies_throttling_and_auth():
    throttled = AnthropicUsageFetchError("http_429", status_code=429)
    unauthorized = AnthropicUsageFetchError("http_401", status_code=401)
    other = AnthropicUsageFetchError("timeout")

    assert throttled.throttled and not throttled.unauthorized
    assert unauthorized.unauthorized and not unauthorized.throttled
    assert not other.throttled and not other.unauthorized

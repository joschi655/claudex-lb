from __future__ import annotations

from app.core.anthropic.usage_headers import parse_rate_limits, parse_reset_at

pytestmark_names = ("unit",)


def test_parses_standard_request_and_token_limits() -> None:
    snapshots = parse_rate_limits(
        {
            "anthropic-ratelimit-requests-limit": "1000",
            "anthropic-ratelimit-requests-remaining": "750",
            "anthropic-ratelimit-requests-reset": "2030-01-02T03:04:05Z",
            "anthropic-ratelimit-input-tokens-limit": "20000",
            "anthropic-ratelimit-input-tokens-remaining": "5000",
            "anthropic-ratelimit-input-tokens-reset": "2030-01-02T03:05:00+00:00",
        }
    )

    assert [(snapshot.quota_key, snapshot.used_percent) for snapshot in snapshots] == [
        ("anthropic_requests", 25.0),
        ("anthropic_input_tokens", 75.0),
    ]
    assert snapshots[0].reset_at == 1_893_553_445
    assert snapshots[1].reset_at == 1_893_553_500


def test_headers_are_case_insensitive() -> None:
    snapshots = parse_rate_limits(
        {
            "Anthropic-RateLimit-Tokens-Limit": "100",
            "Anthropic-RateLimit-Tokens-Remaining": "42",
        }
    )
    assert len(snapshots) == 1
    assert snapshots[0].quota_key == "anthropic_tokens"
    assert snapshots[0].used_percent == 58.0


def test_missing_or_malformed_pairs_are_ignored() -> None:
    assert parse_rate_limits({"content-type": "application/json"}) == ()
    assert (
        parse_rate_limits(
            {
                "anthropic-ratelimit-requests-limit": "not-a-number",
                "anthropic-ratelimit-requests-remaining": "5",
                "anthropic-ratelimit-tokens-limit": "0",
                "anthropic-ratelimit-tokens-remaining": "0",
            }
        )
        == ()
    )


def test_remaining_is_clamped_to_limit() -> None:
    snapshots = parse_rate_limits(
        {
            "anthropic-ratelimit-output-tokens-limit": "100",
            "anthropic-ratelimit-output-tokens-remaining": "150",
        }
    )
    assert snapshots[0].used_percent == 0.0


def test_reset_parser_accepts_rfc3339_and_epoch() -> None:
    assert parse_reset_at("2030-01-02T03:04:05Z") == 1_893_553_445
    assert parse_reset_at("1893553445") == 1_893_553_445
    assert parse_reset_at("bogus") is None


def test_non_finite_headers_are_ignored() -> None:
    assert parse_reset_at("nan") is None
    assert parse_reset_at("inf") is None
    assert parse_reset_at("-inf") is None
    assert (
        parse_rate_limits(
            {
                "anthropic-ratelimit-requests-limit": "inf",
                "anthropic-ratelimit-requests-remaining": "0",
                "anthropic-ratelimit-tokens-limit": "100",
                "anthropic-ratelimit-tokens-remaining": "nan",
            }
        )
        == ()
    )

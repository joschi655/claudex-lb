"""Hard account pin: openspec/specs/account-routing/spec.md."""

from __future__ import annotations

import pytest

from app.core.balancer.logic import (
    HEALTH_TIER_DRAINING,
    HEALTH_TIER_HEALTHY,
    ROUTING_POLICY_BURN_FIRST,
    ROUTING_POLICY_NORMAL,
    ROUTING_POLICY_PRESERVE,
    SECONDARY_WINDOW_MINUTES,
    AccountState,
    select_account,
)
from app.db.models import AccountStatus

NOW = 1_800_000_000.0
PRIMARY_WINDOW_MINUTES = 300  # the 5h window


def _primary_reset_after(fraction_elapsed: float) -> int:
    length = PRIMARY_WINDOW_MINUTES * 60
    return int(NOW + length * (1.0 - fraction_elapsed))


def _secondary_reset_after(fraction_elapsed: float) -> int:
    length = SECONDARY_WINDOW_MINUTES * 60
    return int(NOW + length * (1.0 - fraction_elapsed))


def _state(account_id: str, **overrides: object) -> AccountState:
    base = {
        "account_id": account_id,
        "status": AccountStatus.ACTIVE,
        "used_percent": 0.0,
        "primary_reset_at": _primary_reset_after(0.5),
        "primary_window_minutes": PRIMARY_WINDOW_MINUTES,
        "secondary_used_percent": 0.0,
        "secondary_reset_at": _secondary_reset_after(0.5),
    }
    base.update(overrides)
    return AccountState(**base)  # type: ignore[arg-type]


def _pick(*states: AccountState, **kwargs: object) -> str | None:
    result = select_account(list(states), now=NOW, **kwargs)  # type: ignore[arg-type]
    return result.account.account_id if result.account else None


class TestPinBeatsRanking:
    def test_pin_wins_over_a_less_used_peer(self) -> None:
        pinned = _state("pinned", pinned=True, used_percent=80.0)
        idle = _state("idle", used_percent=1.0)
        assert _pick(pinned, idle) == "pinned"

    def test_pin_wins_over_burn_first(self) -> None:
        pinned = _state("pinned", pinned=True, used_percent=80.0)
        burn = _state("burn", routing_policy=ROUTING_POLICY_BURN_FIRST, used_percent=1.0)
        assert _pick(pinned, burn) == "pinned"

    def test_pin_wins_from_a_worse_health_tier(self) -> None:
        pinned = _state("pinned", pinned=True, health_tier=HEALTH_TIER_DRAINING)
        healthy = _state("healthy", health_tier=HEALTH_TIER_HEALTHY)
        assert _pick(pinned, healthy) == "pinned"

    @pytest.mark.parametrize(
        "strategy",
        ["usage_weighted", "round_robin", "fill_first", "capacity_weighted", "relative_availability"],
    )
    def test_pin_wins_under_every_ranking_strategy(self, strategy: str) -> None:
        pinned = _state("pinned", pinned=True, used_percent=90.0)
        idle = _state("idle", used_percent=0.0)
        assert _pick(pinned, idle, routing_strategy=strategy, deterministic_probe=True) == "pinned"

    def test_pin_wins_over_a_preserve_peer_without_reading_preserve_floors(self) -> None:
        pinned = _state("pinned", pinned=True, used_percent=99.0)
        kept = _state("kept", routing_policy=ROUTING_POLICY_PRESERVE, used_percent=0.0)
        assert _pick(pinned, kept) == "pinned"


class TestPinBeatsPaceGates:
    def test_pace_gated_pin_still_serves(self) -> None:
        # 5h window half elapsed -> even-pace line 50%; 60% with a 20pt margin
        # is a clear gate failure for any unpinned account.
        pinned = _state(
            "pinned",
            pinned=True,
            used_percent=60.0,
            pace_margin_primary_pct=20.0,
        )
        peer = _state("peer", used_percent=0.0)
        assert _pick(pinned, peer) == "pinned"

    def test_the_same_gate_still_excludes_an_unpinned_account(self) -> None:
        gated = _state("gated", used_percent=60.0, pace_margin_primary_pct=20.0)
        peer = _state("peer", used_percent=0.0)
        assert _pick(gated, peer) == "peer"

    def test_pre_reset_window_does_not_hold_back_a_pin(self) -> None:
        pinned = _state(
            "pinned",
            pinned=True,
            pre_reset_window_minutes=10,
            primary_reset_at=_primary_reset_after(0.0),
        )
        peer = _state("peer")
        assert _pick(pinned, peer) == "pinned"

    def test_secondary_pace_gate_does_not_hold_back_a_pin(self) -> None:
        pinned = _state(
            "pinned",
            pinned=True,
            secondary_used_percent=70.0,
            pace_margin_secondary_pct=20.0,
        )
        peer = _state("peer")
        assert _pick(pinned, peer) == "pinned"


class TestExhaustedPinReleases:
    @pytest.mark.parametrize(
        "overrides",
        [
            {"status": AccountStatus.QUOTA_EXCEEDED, "reset_at": int(NOW + 3600)},
            {"status": AccountStatus.RATE_LIMITED, "reset_at": int(NOW + 3600)},
            {"status": AccountStatus.PAUSED},
            {"status": AccountStatus.REAUTH_REQUIRED},
            {"status": AccountStatus.DEACTIVATED},
            {"cooldown_until": NOW + 600},
        ],
        ids=["quota", "rate_limit", "paused", "reauth", "deactivated", "cooldown"],
    )
    def test_an_unserviceable_pin_hands_over_to_the_pool(self, overrides: dict[str, object]) -> None:
        pinned = _state("pinned", pinned=True, **overrides)
        peer = _state("peer")
        assert _pick(pinned, peer) == "peer"
        # Release is not clearing: the marking the operator set is untouched.
        assert pinned.pinned is True

    def test_a_pin_in_error_backoff_hands_over(self) -> None:
        pinned = _state(
            "pinned",
            pinned=True,
            error_count=5,
            last_error_at=NOW - 1.0,
        )
        peer = _state("peer")
        assert _pick(pinned, peer) == "peer"

    def test_the_pin_resumes_once_the_window_resets(self) -> None:
        pinned = _state(
            "pinned",
            pinned=True,
            status=AccountStatus.QUOTA_EXCEEDED,
            reset_at=int(NOW - 1),
        )
        peer = _state("peer")
        assert _pick(pinned, peer) == "pinned"

    def test_an_unserviceable_pin_alone_reports_the_usual_diagnosis(self) -> None:
        pinned = _state("pinned", pinned=True, status=AccountStatus.PAUSED)
        result = select_account([pinned], now=NOW)
        assert result.account is None
        assert result.error_message == "All accounts are paused"


class TestPinDoesNotBypassScope:
    def test_a_pin_outside_the_candidate_list_has_no_effect(self) -> None:
        # The relay hands the selector a pre-scoped list (an API key's assigned
        # accounts, a model filter). A pin the caller did not include is simply
        # absent, and cannot pull the selection back out of scope.
        _pinned_but_out_of_scope = _state("pinned", pinned=True)
        in_scope = [_state("peer"), _state("other", used_percent=50.0)]
        assert {_pick(*in_scope) for _ in range(50)} == {"peer", "other"}

    def test_two_pins_never_fall_out_of_the_pinned_set(self) -> None:
        # Exclusivity is enforced at the write, not here. The selector only has
        # to degrade sanely: choose between the pins, never around them.
        first = _state("aaa", pinned=True, used_percent=90.0)
        second = _state("bbb", pinned=True, used_percent=1.0)
        idle = _state("idle", used_percent=0.0)
        assert {_pick(first, second, idle) for _ in range(50)} <= {"aaa", "bbb"}

    def test_an_unpinned_pool_is_unchanged(self) -> None:
        burn = _state("burn", routing_policy=ROUTING_POLICY_BURN_FIRST, used_percent=50.0)
        plain = _state("plain", routing_policy=ROUTING_POLICY_NORMAL, used_percent=0.0)
        assert _pick(burn, plain) == "burn"

"""Per-account usage ceilings and per-key routing rules: openspec/specs/account-routing/spec.md."""

from __future__ import annotations

from dataclasses import replace
from typing import Any

import pytest

from app.core.balancer.logic import (
    ROUTING_POLICY_BURN_FIRST,
    ROUTING_POLICY_PRESERVE,
    AccountState,
    evaluate_usage_ceilings,
    select_account,
)
from app.core.balancer.routing_rules import AccountRoutingRule, apply_routing_rule
from app.db.models import AccountStatus

NOW = 1_800_000_000.0


def _state(account_id: str = "a", **overrides: Any) -> AccountState:
    base = AccountState(
        account_id=account_id,
        status=AccountStatus.ACTIVE,
        used_percent=10.0,
        primary_reset_at=int(NOW + 3600),
        primary_window_minutes=300,
        secondary_used_percent=10.0,
        secondary_reset_at=int(NOW + 3 * 86400),
    )
    return replace(base, **overrides)


def _selected(states: list[AccountState]) -> str | None:
    result = select_account(states, NOW)
    return None if result.account is None else result.account.account_id


class TestEvaluateUsageCeilings:
    @pytest.mark.parametrize(
        ("used_pct", "expected"),
        [(79.9, None), (80.0, "primary_ceiling"), (95.0, "primary_ceiling")],
    )
    def test_primary_ceiling_is_inclusive(self, used_pct: float, expected: str | None) -> None:
        state = _state(usage_ceiling_primary_pct=80.0, used_percent=used_pct)
        assert evaluate_usage_ceilings(state, NOW) == expected

    def test_secondary_ceiling(self) -> None:
        state = _state(usage_ceiling_secondary_pct=70.0, secondary_used_percent=70.5)
        assert evaluate_usage_ceilings(state, NOW) == "secondary_ceiling"

    def test_unset_ceiling_never_excludes(self) -> None:
        assert evaluate_usage_ceilings(_state(used_percent=99.0, secondary_used_percent=99.0), NOW) is None

    def test_unknown_usage_passes(self) -> None:
        state = _state(usage_ceiling_primary_pct=50.0, used_percent=None)
        assert evaluate_usage_ceilings(state, NOW) is None

    def test_sample_from_a_rolled_over_window_passes(self) -> None:
        # The 85% belongs to a window that reset a minute ago.
        state = _state(usage_ceiling_primary_pct=80.0, used_percent=85.0, primary_reset_at=int(NOW - 60))
        assert evaluate_usage_ceilings(state, NOW) is None


class TestCeilingsInSelection:
    def test_account_at_ceiling_is_skipped(self) -> None:
        capped = _state("capped", usage_ceiling_primary_pct=80.0, used_percent=81.0)
        spare = _state("spare", used_percent=60.0)
        result = select_account([capped, spare], NOW, routing_strategy="usage_weighted")
        assert result.account is not None
        assert result.account.account_id == "spare"

    def test_burn_first_does_not_lift_a_ceiling(self) -> None:
        capped = _state(
            "capped",
            routing_policy=ROUTING_POLICY_BURN_FIRST,
            usage_ceiling_secondary_pct=50.0,
            secondary_used_percent=50.0,
        )
        spare = _state("spare")
        result = select_account([capped, spare], NOW)
        assert result.account is not None
        assert result.account.account_id == "spare"

    def test_pin_does_not_lift_a_ceiling(self) -> None:
        pinned = _state("pinned", pinned=True, usage_ceiling_primary_pct=80.0, used_percent=90.0)
        spare = _state("spare")
        result = select_account([pinned, spare], NOW)
        assert result.account is not None
        assert result.account.account_id == "spare"

    def test_pin_still_lifts_pace_gates_below_its_ceiling(self) -> None:
        pinned = _state(
            "pinned", pinned=True, usage_ceiling_primary_pct=90.0, used_percent=70.0, pace_margin_primary_pct=50.0
        )
        spare = _state("spare")
        result = select_account([pinned, spare], NOW)
        assert result.account is not None
        assert result.account.account_id == "pinned"

    def test_whole_pool_at_ceiling_names_the_ceiling(self) -> None:
        states = [
            _state("a", usage_ceiling_primary_pct=80.0, used_percent=80.0),
            _state("b", usage_ceiling_secondary_pct=60.0, secondary_used_percent=75.0),
        ]
        result = select_account(states, NOW)
        assert result.account is None
        assert result.error_message == (
            "All accounts are held at their usage ceilings (primary_ceiling, secondary_ceiling)"
        )


class TestRoutingRules:
    def test_missing_rule_changes_nothing(self) -> None:
        state = _state(routing_policy=ROUTING_POLICY_PRESERVE, usage_ceiling_primary_pct=80.0)
        apply_routing_rule(state, None)
        assert state.routing_policy == ROUTING_POLICY_PRESERVE
        assert state.usage_ceiling_primary_pct == 80.0

    def test_policy_override_keeps_inherited_gates(self) -> None:
        state = _state(usage_ceiling_primary_pct=80.0, pace_margin_secondary_pct=10.0)
        apply_routing_rule(state, AccountRoutingRule(account_id="a", routing_policy=ROUTING_POLICY_BURN_FIRST))
        assert state.routing_policy == ROUTING_POLICY_BURN_FIRST
        assert state.usage_ceiling_primary_pct == 80.0
        assert state.pace_margin_secondary_pct == 10.0

    def test_gate_override_replaces_all_gates_and_none_switches_off(self) -> None:
        state = _state(usage_ceiling_primary_pct=80.0, pace_margin_secondary_pct=10.0, pre_reset_window_minutes=60)
        apply_routing_rule(
            state,
            AccountRoutingRule(account_id="a", override_gates=True, usage_ceiling_secondary_pct=95.0),
        )
        assert state.usage_ceiling_primary_pct is None
        assert state.usage_ceiling_secondary_pct == 95.0
        assert state.pace_margin_secondary_pct is None
        assert state.pre_reset_window_minutes is None

    def test_two_keys_route_the_same_pool_differently(self) -> None:
        def pool() -> list[AccountState]:
            return [
                _state("owner-seat", usage_ceiling_primary_pct=80.0, used_percent=85.0),
                _state("my-seat", used_percent=30.0),
            ]

        # Key 1 keeps the owner's reserve and burns its own seat first.
        key_one = pool()
        apply_routing_rule(
            key_one[1], AccountRoutingRule(account_id="my-seat", routing_policy=ROUTING_POLICY_BURN_FIRST)
        )
        assert _selected(key_one) == "my-seat"

        # Key 2 may use the owner seat to 100% and prefers it.
        key_two = pool()
        apply_routing_rule(
            key_two[0],
            AccountRoutingRule(account_id="owner-seat", routing_policy=ROUTING_POLICY_BURN_FIRST, override_gates=True),
        )
        assert _selected(key_two) == "owner-seat"

"""Per-account pace gates: openspec/specs/account-routing/spec.md."""

from __future__ import annotations

import pytest

from app.core.balancer.logic import (
    ROUTING_POLICY_BURN_FIRST,
    SECONDARY_WINDOW_MINUTES,
    AccountState,
    evaluate_pace_gates,
    select_account,
)
from app.db.models import AccountStatus

NOW = 1_800_000_000.0
PRIMARY_WINDOW_MINUTES = 300  # the 5h window


def _primary_reset_after(fraction_elapsed: float) -> int:
    """Reset timestamp placing the primary window ``fraction_elapsed`` through."""
    length = PRIMARY_WINDOW_MINUTES * 60
    return int(NOW + length * (1.0 - fraction_elapsed))


def _secondary_reset_after(fraction_elapsed: float) -> int:
    length = SECONDARY_WINDOW_MINUTES * 60
    return int(NOW + length * (1.0 - fraction_elapsed))


def _state(**overrides: object) -> AccountState:
    base = {
        "account_id": "a",
        "status": AccountStatus.ACTIVE,
        "used_percent": 0.0,
        "primary_reset_at": _primary_reset_after(0.5),
        "primary_window_minutes": PRIMARY_WINDOW_MINUTES,
        "secondary_used_percent": 0.0,
        "secondary_reset_at": _secondary_reset_after(0.5),
    }
    base.update(overrides)
    return AccountState(**base)  # type: ignore[arg-type]


class TestEvenPaceLine:
    @pytest.mark.parametrize(
        ("fraction_elapsed", "used_pct", "expected_gate"),
        [
            (0.0, 0.0, None),  # window start: pace line 0, zero usage passes
            (0.0, 0.1, "primary_pace"),  # anything above 0 is ahead at the start
            (0.5, 50.0, None),  # exactly on the line passes at margin 0
            (0.5, 50.1, "primary_pace"),
            (1.0, 100.0, None),  # window end: the whole budget is on schedule
        ],
    )
    def test_margin_zero_tracks_the_line(
        self, fraction_elapsed: float, used_pct: float, expected_gate: str | None
    ) -> None:
        state = _state(
            pace_margin_primary_pct=0.0,
            used_percent=used_pct,
            primary_reset_at=_primary_reset_after(fraction_elapsed),
        )
        assert evaluate_pace_gates(state, NOW) == expected_gate

    def test_elapsed_past_reset_is_clamped_to_a_full_window(self) -> None:
        # A reset timestamp in the past means the window already rolled over;
        # the pace line must clamp to 100 rather than run past it.
        state = _state(
            pace_margin_primary_pct=0.0,
            used_percent=99.0,
            primary_reset_at=int(NOW - 60),
        )
        assert evaluate_pace_gates(state, NOW) is None


class TestIndividualGates:
    def test_below_line_by_more_than_the_margin_passes(self) -> None:
        # Half the week elapsed puts the line at 50%; 25% is 25 points below.
        state = _state(pace_margin_secondary_pct=20.0, secondary_used_percent=25.0)
        assert evaluate_pace_gates(state, NOW) is None

    def test_inside_the_margin_fails(self) -> None:
        state = _state(pace_margin_secondary_pct=20.0, secondary_used_percent=35.0)
        assert evaluate_pace_gates(state, NOW) == "secondary_pace"

    def test_pre_reset_window_admits_only_near_the_reset(self) -> None:
        inside = _state(pre_reset_window_minutes=120, primary_reset_at=int(NOW + 90 * 60))
        outside = _state(pre_reset_window_minutes=120, primary_reset_at=int(NOW + 200 * 60))
        assert evaluate_pace_gates(inside, NOW) is None
        assert evaluate_pace_gates(outside, NOW) == "pre_reset_window"

    def test_unset_gates_never_exclude(self) -> None:
        assert evaluate_pace_gates(_state(used_percent=99.0, secondary_used_percent=99.0), NOW) is None


class TestNotEvaluable:
    def test_missing_reset_does_not_exclude(self) -> None:
        state = _state(pace_margin_primary_pct=50.0, used_percent=100.0, primary_reset_at=None)
        assert evaluate_pace_gates(state, NOW) is None

    def test_missing_window_length_does_not_exclude(self) -> None:
        state = _state(pace_margin_primary_pct=50.0, used_percent=100.0, primary_window_minutes=None)
        assert evaluate_pace_gates(state, NOW) is None

    def test_missing_primary_reset_does_not_exclude_pre_reset_gate(self) -> None:
        assert evaluate_pace_gates(_state(pre_reset_window_minutes=10, primary_reset_at=None), NOW) is None

    def test_absent_usage_counts_as_zero(self) -> None:
        state = _state(pace_margin_primary_pct=20.0, used_percent=None)
        assert evaluate_pace_gates(state, NOW) is None


class TestConjunction:
    def test_one_failing_gate_excludes(self) -> None:
        state = _state(
            pace_margin_primary_pct=10.0,
            pace_margin_secondary_pct=20.0,
            pre_reset_window_minutes=200,
            used_percent=10.0,  # passes: line 50, margin 10
            secondary_used_percent=45.0,  # fails: line 50, margin 20
        )
        assert evaluate_pace_gates(state, NOW) == "secondary_pace"

    def test_all_gates_satisfied_passes(self) -> None:
        state = _state(
            pace_margin_primary_pct=10.0,
            pace_margin_secondary_pct=20.0,
            pre_reset_window_minutes=200,
            used_percent=10.0,
            secondary_used_percent=10.0,
        )
        assert evaluate_pace_gates(state, NOW) is None


class TestSelectionIntegration:
    def test_gated_account_is_not_selected(self) -> None:
        gated = _state(account_id="gated", pace_margin_primary_pct=20.0, used_percent=45.0)
        open_account = _state(account_id="open", used_percent=45.0)
        result = select_account([gated, open_account], now=NOW)
        assert result.account is not None
        assert result.account.account_id == "open"

    def test_burn_first_cannot_re_admit_a_gated_account(self) -> None:
        gated = _state(
            account_id="gated",
            routing_policy=ROUTING_POLICY_BURN_FIRST,
            pace_margin_primary_pct=20.0,
            used_percent=45.0,
        )
        open_account = _state(account_id="open", used_percent=45.0)
        result = select_account([gated, open_account], now=NOW)
        assert result.account is not None
        assert result.account.account_id == "open"

    def test_all_gated_reports_pace_gating(self) -> None:
        states = [
            _state(account_id="a", pace_margin_primary_pct=20.0, used_percent=45.0),
            _state(account_id="b", pre_reset_window_minutes=10),
        ]
        result = select_account(states, now=NOW)
        assert result.account is None
        assert result.error_message is not None
        assert "pace gates" in result.error_message

    def test_gated_account_does_not_colour_the_blocked_message(self) -> None:
        # The paused account is the only actionable blocker, so the message must
        # name it rather than reporting on the gated one.
        states = [
            _state(account_id="gated", pace_margin_primary_pct=20.0, used_percent=45.0),
            _state(account_id="paused", status=AccountStatus.PAUSED),
        ]
        result = select_account(states, now=NOW)
        assert result.account is None
        assert result.error_message == "All accounts are paused"

    def test_no_gates_configured_leaves_selection_unchanged(self) -> None:
        states = [_state(account_id="a", used_percent=80.0), _state(account_id="b", used_percent=10.0)]
        result = select_account(states, now=NOW, routing_strategy="fill_first")
        assert result.account is not None

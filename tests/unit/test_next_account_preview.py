"""Which account serves next, as opposed to which one served last.

Contract: openspec/changes/show-the-next-serving-account/specs/account-routing/spec.md.
"""

from __future__ import annotations

import time

import pytest

from app.core.balancer.logic import (
    HEALTH_TIER_DRAINING,
    AccountState,
    select_account,
)
from app.db.models import AccountStatus
from app.modules.proxy.load_balancer import (
    _RANDOMIZED_ROUTING_STRATEGIES,
    _preview_is_certain,
)

pytestmark = pytest.mark.unit


def _state(account_id: str, **overrides) -> AccountState:
    fields = {
        "status": AccountStatus.ACTIVE,
        "used_percent": 10.0,
        "secondary_used_percent": 10.0,
    }
    fields.update(overrides)
    return AccountState(account_id, **fields)


def _next_up(states: list[AccountState], **kwargs) -> str | None:
    """The preview's core: the pure selector, probed deterministically."""
    result = select_account(list(states), deterministic_probe=True, **kwargs)
    return result.account.account_id if result.account else None


def test_the_preview_is_stable_across_repeated_calls() -> None:
    """A preview that moved on every poll would be worse than no preview."""
    states = [_state("a", used_percent=40.0), _state("b", used_percent=10.0), _state("c", used_percent=70.0)]

    answers = {_next_up(states) for _ in range(50)}

    assert len(answers) == 1


def test_the_least_used_account_is_next_under_capacity_weighting() -> None:
    states = [_state("busy", used_percent=80.0), _state("idle", used_percent=5.0)]

    assert _next_up(states) == "idle"


def test_a_pin_is_next_even_when_a_peer_is_emptier() -> None:
    """The pin is the operator overriding the ranking, so it wins the preview."""
    states = [_state("emptier", used_percent=1.0), _state("held", used_percent=85.0, pinned=True)]

    assert _next_up(states) == "held"


def test_a_pin_wins_the_preview_from_a_worse_health_tier() -> None:
    states = [
        _state("healthy", used_percent=5.0),
        _state("held", used_percent=50.0, pinned=True, health_tier=HEALTH_TIER_DRAINING),
    ]

    assert _next_up(states) == "held"


def test_a_paused_account_is_never_next() -> None:
    """The case a last-served view gets wrong: it keeps naming the account that
    just stopped being eligible."""
    states = [_state("paused", used_percent=1.0, status=AccountStatus.PAUSED), _state("live", used_percent=90.0)]

    assert _next_up(states) == "live"


def test_an_empty_pool_reports_no_next_account() -> None:
    assert _next_up([]) is None


def test_every_account_gated_reports_no_next_account() -> None:
    states = [_state("paused", status=AccountStatus.PAUSED)]

    assert _next_up(states) is None


def test_a_gated_account_is_not_next() -> None:
    """Gated accounts are not candidates at all, so the preview must skip them.

    Uses the pre-reset gate because it needs only a reset timestamp: a reset four
    hours out with a one-hour window excludes the account outright, which is the
    exact shape that once left julius unable to serve while the menu bar still
    named it.
    """
    states = [
        _state(
            "gated",
            used_percent=5.0,
            primary_reset_at=int(time.time()) + 4 * 3600,
            pre_reset_window_minutes=60,
        ),
        _state("open", used_percent=95.0),
    ]

    assert _next_up(states) == "open"


@pytest.mark.parametrize("strategy", sorted(_RANDOMIZED_ROUTING_STRATEGIES))
def test_the_randomized_strategies_are_the_ones_flagged_uncertain(strategy: str) -> None:
    """Guards the premise behind the ``certain`` flag.

    These two draw at random among weighted candidates, so a preview of them is a
    front-runner rather than a promise. Every other strategy takes the minimum of
    a sort key. If that ever stops being true, this list is what has to change.
    """
    states = [_state("a", used_percent=10.0), _state("b", used_percent=11.0)]
    without_probe = {select_account(list(states), routing_strategy=strategy).account.account_id for _ in range(200)}

    assert len(without_probe) > 1


def test_a_deterministic_strategy_needs_no_hedge() -> None:
    states = [_state("a", used_percent=10.0), _state("b", used_percent=11.0)]

    answers = {select_account(list(states), routing_strategy="round_robin").account.account_id for _ in range(50)}

    assert len(answers) == 1
    assert "round_robin" not in _RANDOMIZED_ROUTING_STRATEGIES


class TestPreviewCertainty:
    """Whether the previewed account is the answer or just the front-runner.

    Read from the account that was *selected*, never from the pool that was
    offered: ``select_account`` applies the pin over the accounts that survived
    eligibility, so a pinned account that is rate limited leaves the pool
    ranking normally. Asking "is anything pinned?" instead reports a coin flip
    as a certainty in exactly the case the pin exists for -- the pinned window
    running out.
    """

    def test_a_serving_pin_makes_the_answer_exact(self) -> None:
        held = _state("held", pinned=True)
        states = [held, _state("other")]

        assert _preview_is_certain("capacity_weighted", states, held) is True

    def test_a_pin_that_did_not_decide_does_not_make_the_answer_exact(self) -> None:
        # The pin is in the pool but lost eligibility, so the selector ranked
        # normally and the real request will draw at random.
        held = _state("held", pinned=True, status=AccountStatus.RATE_LIMITED)
        chosen = _state("chosen")
        states = [held, chosen, _state("third")]

        assert _preview_is_certain("capacity_weighted", states, chosen) is False

    def test_a_single_candidate_has_nothing_to_draw_between(self) -> None:
        only = _state("only")

        assert _preview_is_certain("capacity_weighted", [only], only) is True

    def test_a_deterministic_strategy_is_exact_without_a_pin(self) -> None:
        chosen = _state("chosen")

        assert _preview_is_certain("round_robin", [chosen, _state("other")], chosen) is True

    def test_a_weighted_draw_over_several_accounts_is_a_front_runner(self) -> None:
        chosen = _state("chosen")

        assert _preview_is_certain("capacity_weighted", [chosen, _state("other")], chosen) is False

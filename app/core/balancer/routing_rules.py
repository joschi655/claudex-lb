"""Per-API-key overrides of how an account is ranked and gated.

One pool can serve several devices, each with its own key and its own idea of
which seats to spend first and how far. A rule rewrites the request-scoped
``AccountState`` the selector reads, and nothing else: the stored account, its
runtime bookkeeping and every other key's view stay untouched. See the
``account-routing`` capability for the normative contract.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

from app.core.balancer.logic import (
    ROUTING_POLICY_BURN_FIRST,
    ROUTING_POLICY_NORMAL,
    ROUTING_POLICY_PRESERVE,
    AccountState,
)

ROUTING_RULE_POLICIES = frozenset({ROUTING_POLICY_BURN_FIRST, ROUTING_POLICY_NORMAL, ROUTING_POLICY_PRESERVE})


@dataclass(frozen=True, slots=True)
class AccountRoutingRule:
    account_id: str
    # None inherits the account's own policy.
    routing_policy: str | None = None
    # False inherits the account's gates and ignores the five fields below. True
    # replaces them wholesale, and None there switches that gate off for the key.
    override_gates: bool = False
    usage_ceiling_primary_pct: float | None = None
    usage_ceiling_secondary_pct: float | None = None
    pace_margin_primary_pct: float | None = None
    pace_margin_secondary_pct: float | None = None
    pre_reset_window_minutes: int | None = None


AccountRoutingRules = Mapping[str, AccountRoutingRule]


def apply_routing_rule(state: AccountState, rule: AccountRoutingRule | None) -> None:
    if rule is None:
        return
    if rule.routing_policy in ROUTING_RULE_POLICIES:
        state.routing_policy = rule.routing_policy
    if rule.override_gates:
        state.usage_ceiling_primary_pct = rule.usage_ceiling_primary_pct
        state.usage_ceiling_secondary_pct = rule.usage_ceiling_secondary_pct
        state.pace_margin_primary_pct = rule.pace_margin_primary_pct
        state.pace_margin_secondary_pct = rule.pace_margin_secondary_pct
        state.pre_reset_window_minutes = rule.pre_reset_window_minutes

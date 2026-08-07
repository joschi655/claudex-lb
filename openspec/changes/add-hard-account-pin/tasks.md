# Tasks

## 1. Policy value

- [x] 1.1 Add `PINNED = "pinned"` to `AccountRoutingPolicy` in `app/db/models.py`
- [x] 1.2 Accept `pinned` in the account read/update schemas and in the mapper's
      known-policy set. Leave the additional-quota routing policy alone: a pin is an
      account-level statement and has no meaning per quota pool.
- [x] 1.3 Clear the pin from other accounts of the same provider when one is pinned

## 2. Selection

- [x] 2.1 Add `ROUTING_POLICY_PINNED` and a `hard_pinned` helper in
      `app/core/balancer/logic.py`
- [x] 2.2 Exempt a pinned account from the pace-gate filter in the `select_account`
      availability loop
- [x] 2.3 Narrow `available` to the pinned account once the availability loop and the
      backoff-fallback path have run, so the pin bypasses health and policy tiers but
      not eligibility
- [x] 2.4 Try the pin first in `_select_account_preferring_budget_safe`, ahead of
      `_best_health_tier_states`, and fall through when it yields no account
- [x] 2.5 Let a pin outrank a sticky-session mapping that points at a different account

## 3. Frontend

- [x] 3.1 Add `pinned` to the account routing-policy enums in
      `frontend/src/features/accounts/schemas.ts`
- [x] 3.2 Offer it in the routing-policy select in `account-actions.tsx`
- [x] 3.3 Render it in `account-list-item.tsx`
- [ ] 3.4 Before/after screenshots on the PR

## 4. Menu bar

- [ ] 4.1 Switch `cmdSwitch` in `scripts/swiftbar/claudex-lb.1m.ts` to set `pinned`,
      and treat `pinned` as the pin marker when rendering
- [ ] 4.2 Read the serving account from the request log rather than from the pin, and
      say when the two disagree

## 5. Tests

- [x] 5.1 Unit: a pinned account serves while a healthier, less-used peer is available
- [x] 5.2 Unit: a pinned account serves while it is pace-gated
- [x] 5.3 Unit: a pinned account in a worse health tier still serves
- [x] 5.4 Unit: a pinned account that is paused / rate limited / quota exceeded /
      in cooldown releases to the automatic rules, and the pin survives
- [x] 5.5 Unit: a pinned account ineligible for the requested model does not force
- [x] 5.6 Unit: the budget-safe preference path honours the pin, and falls through
- [x] 5.7 Unit: a sticky mapping to another account does not beat the pin
- [x] 5.8 API: pinning clears the pin on other accounts of the same provider and
      leaves the other provider's pin alone

## 6. Docs

- [x] 6.1 `docs/` page describing the pin and the exact list of conditions that release
      it, linking back to `openspec/specs/account-routing/`

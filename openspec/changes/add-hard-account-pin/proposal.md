## Why

Operators reach for a "use this account" control when they want traffic on one seat and
nowhere else — a seat they just topped up, a seat they are testing, a seat whose owner
has agreed to carry today's load. The pool has no such control. The nearest thing is
routing policy `burn_first`, which is a *ranking tier*, not an override: it only
reorders accounts that have already survived every hard filter ahead of it.

That distinction is invisible from the outside and produces the reverse of the intended
result. An account marked `burn_first` is skipped whenever it is pace-gated, whenever it
sits in a worse health tier than a peer, and whenever the budget-safe preference path
picks a different tier first — and the pool quietly serves someone else while the UI
still shows the mark. `burn_first` also carries the opposite meaning upstream: it labels
an account as *expendable*, to be drained ahead of the ones worth keeping. Reusing it as
a pin overloads one field with two intents that disagree about what should happen when
the marked account is under pressure.

## What Changes

- A fourth account routing policy, `pinned`, expressing "serve this account, and only
  this account, for as long as it can serve".
- A pinned account is the sole selection candidate whenever it is *able* to serve. Pace
  gates, health tiers, routing-policy tiers, the budget-safe preference path, and
  session stickiness no longer route around it.
- A pinned account that *cannot* serve — paused, deactivated, needs re-auth, quota
  exceeded, rate limited, in cooldown or error backoff, or ineligible for the requested
  model or additional quota — releases selection to the existing automatic rules over
  the remaining accounts, unchanged.
- Release is temporary. The pin persists across the outage and resumes as soon as the
  account can serve again; only an operator clears it.
- At most one account per provider may be pinned. Pinning an account clears the pin from
  every other account of the same provider, so the control cannot be left ambiguous.
- The dashboard account actions and the account list expose and render the new value.

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `account-routing`: routing policy gains `pinned`, which acts as a hard selection
  override rather than a ranking tier, and yields to the automatic rules when the pinned
  account cannot serve.

## Impact

- Code: `app/core/balancer/logic.py`, `app/modules/proxy/load_balancer.py`,
  `app/db/models.py`, `app/modules/accounts/{schemas,mappers,service,repository,api}.py`
- Frontend: `frontend/src/features/accounts/{schemas.ts,components/account-actions.tsx,components/account-list-item.tsx}`
- Migration: none. `accounts.routing_policy` is a plain string column with an
  application-level value set; existing rows are untouched.
- Tests: `tests/unit/test_balancer_logic.py`, `tests/unit/test_account_hard_pin.py`,
  `tests/integration/test_accounts_api_routing_policy.py`
- Specs: `openspec/specs/account-routing/spec.md`

## Simplicity

No new `CODEX_LB_*` setting: the pin is per-account state on a column that already
exists, set through the routing-policy endpoint that already exists. An installation
that never pins keeps its current selection behavior byte for byte, because every new
branch is guarded on a policy value no existing row holds. No new README section;
operator documentation goes to `docs/` with a link back to this capability.

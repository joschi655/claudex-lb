## Why

Two controls in the dashboard answer a question nobody asked.

**The pin is stored as a routing policy value.** `pinned` sits in the same
dropdown as `normal`, `burn_first`, and `preserve`, which makes the pin and the
policy mutually exclusive when they are in fact orthogonal: the pin decides
*whether* an account is the only candidate, the policy decides *how hard* to
draw on it once it is one of several. Storing them in one field means pinning a
`preserve` account destroys the fact that it was `preserve` — and unpinning
drops it on `normal`, silently promoting a seat that was deliberately held back.
An operator who pins for an hour cannot get their pool back.

**The "Serving" badge names the account that served last.** It is derived from
the newest request log row, which answers "who went last", not "who goes next".
Those diverge exactly when the answer matters: the moment an account is pinned,
paused, rate limited, or crosses a pace gate, the badge keeps naming it while
the next request lands somewhere else. The same is true of the menu bar. An
operator watching either one to decide whether the pin took effect is reading a
number that will only catch up after traffic has already gone to the wrong seat.

## What Changes

- The pin moves to its own `accounts.pinned` column. Routing policy returns to
  three values, and `pinned` is no longer accepted as one of them.
- Pinning and unpinning leave the routing policy untouched, so an account
  returns to the policy it already had when the pin lifts.
- A new `PUT /api/accounts/{id}/pin` sets the flag, keeping per-provider
  exclusivity. It echoes the routing policy back so a caller that just unpinned
  can see what the account fell back to.
- A new `GET /api/accounts/next-up` reports, per provider, which account a new
  request would land on. It runs the real selector as a dry run: no lease, no
  sticky mapping, nothing persisted.
- The preview reports its own certainty. The default strategy draws at random
  among weighted candidates, so the named account is a front-runner rather than
  a promise; a pin makes it exact.
- The dashboard account list and the menu bar name the next account instead of
  the last one, and the dashboard grows a pin toggle separate from the policy
  dropdown.

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `account-routing`: the pin becomes its own account flag rather than a routing
  policy value, and the pool can be asked which account it would select next
  without selecting it.
- `account-quota-presentation`: the account list identifies the account that
  will serve next rather than the one that served last, and exposes the pin as
  its own control.

## Impact

- Code: `app/db/models.py`, `app/core/balancer/logic.py`,
  `app/modules/proxy/load_balancer.py`, `app/modules/proxy/service.py`,
  `app/modules/anthropic_proxy/service.py`,
  `app/modules/accounts/{schemas,mappers,service,repository,api}.py`
- Migration: `20260811_000000_add_account_pinned_flag` — adds the column and
  carries an existing `routing_policy='pinned'` row over to it. The downgrade
  folds the flag back into the policy so older code still finds the pin.
- Frontend: `frontend/src/features/accounts/{api.ts,schemas.ts,serving.ts,hooks/use-accounts.ts,components/account-actions.tsx,components/account-list.tsx,components/account-list-item.tsx}`
- Menu bar: `scripts/swiftbar/claudex-lb.1m.ts`
- Tests: `tests/unit/{test_account_hard_pin,test_next_account_preview,test_load_balancer,test_select_with_stickiness}.py`,
  `tests/integration/{test_accounts_api_routing_policy,test_account_pin_migration}.py`,
  `frontend/src/features/accounts/**/*.test.{ts,tsx}`
- Specs: `openspec/specs/account-routing/spec.md`,
  `openspec/specs/account-quota-presentation/spec.md`

## Simplicity

No new `CODEX_LB_*` setting. The preview reads the pool that is already running
and adds no state of its own; an installation that never opens the dashboard
never calls it. The pin gains a column but loses a value from an enum, so the
routing policy goes back to meaning one thing. No new README section — operator
documentation goes to `docs/` with a link back to this capability.

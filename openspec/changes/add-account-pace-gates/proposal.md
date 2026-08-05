## Why

Pooled subscription accounts are shared with their original owners. Today the only
per-account controls are the routing policy (`normal` / `burn_first` / `preserve`) and
the *global* sticky budget thresholds on `DashboardSettings`. Neither expresses the
operator intent "this account may contribute to the pool, but never fast enough that
its owner runs out": `burn_first` drains an account as hard as possible, `preserve`
holds it back entirely, and the global thresholds apply the same number to every
account regardless of who owns it.

The missing concept is *pace*. An account that has burned 40% of its weekly quota two
days into the week is ahead of schedule; the same 40% on day six is behind it. A flat
percentage cap cannot distinguish those, so operators are forced to choose between
over-draining an account early in a window and leaving quota unused at the end of one.

## What Changes

- Three optional per-account gates, each defaulting to unset (no behavior change):
  - `pace_margin_primary_pct` — the account is only selectable while its short-window
    (5h) usage sits at least N points below the window's *even-pace line*: the usage it
    would show if the window's quota were consumed at a constant rate.
  - `pace_margin_secondary_pct` — the same test against the weekly window.
  - `pre_reset_window_minutes` — the account is only selectable within N minutes before
    its short-window reset.
- Gates combine with AND, so an operator can express "only in the 2h before the 5h
  reset, only below the 5h pace line, and only 20 points below the weekly pace line".
- Gated-out accounts are removed from the selection pool entirely rather than
  deprioritized, so a gate cannot be silently overridden by a fallback tier.
- Gates are advisory over telemetry, not a security boundary: when the window bounds
  needed to compute a pace line are unknown, the gate does not apply. This is stated
  as a contract because Anthropic window data only arrives with served traffic, and a
  fail-closed reading would strand a freshly imported account permanently.
- The dashboard account API accepts and returns the three fields.

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `account-routing`: per-account pace and reset-window gates are applied as hard
  eligibility filters, alongside the existing routing policy.

## Impact

- Code: `app/core/balancer/logic.py`, `app/modules/proxy/load_balancer.py`,
  `app/db/models.py`, `app/modules/accounts/{schemas,mappers,service,api}.py`
- Migration: new nullable columns on `accounts`
- Tests: `tests/unit/test_balancer_logic.py`, `tests/unit/test_accounts_api.py`
- Specs: `openspec/specs/account-routing/spec.md`

## Simplicity

No new `CODEX_LB_*` settings. All three fields are per-account, nullable, and unset by
default, so an installation that never touches them keeps its current selection
behavior byte for byte. No new README section; operator documentation goes to
`docs/` with a link back to this capability.

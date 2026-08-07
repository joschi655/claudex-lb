# Context

## Why `burn_first` could not be the pin

The pin arrived first as a client convention: the menu-bar plugin's "switch to this
account" wrote `routing_policy = burn_first` and cleared it from the provider's other
accounts. That reads like a pin and is not one.

`burn_first` is applied at the very end of `select_account`, over `health_pool` — a list
that has already been through the pace gates, the status and quota filters, the cooldown
and error-backoff filters, and the health-tier collapse:

```
burn_first    = [s for s in health_pool if policy(s) == "burn_first"]
normal        = [s for s in health_pool if policy(s) == "normal"]
preserve      = [s for s in health_pool if policy(s) == "preserve"]
effective_pool = burn_first or normal or preserve or health_pool
```

Two of those earlier stages routinely remove the very account an operator just marked:

- **Pace gates.** `evaluate_pace_gates` runs at the top of the availability loop,
  deliberately ahead of everything else — its own comment says a gated account must not
  be "re-admitted by a later tier (burn-first, budget-safe, or backoff fallback)". So an
  account with a pace margin set is dropped before the mark is ever read.
- **Health tier.** `health_pool = healthy or probing or draining or available` collapses
  to the best tier present. A marked account sitting in `draining` is invisible whenever
  any peer is `healthy`.

There is a third: `_select_account_preferring_budget_safe` computes
`_best_health_tier_states(...)` before it looks at `burn_first` at all.

The observed failure was exactly this. A seat marked in the menu bar carried
`pre_reset_window_minutes = 60` and `pace_margin_primary_pct = 20`; both gates excluded
it, the pool served a different seat, and the menu bar kept rendering the mark because
the mark is what it reads. Clearing the two gates by hand was the only thing that moved
traffic — which is not a control anyone should have to operate.

`burn_first` also means the opposite of a pin. Upstream it labels an account as
*expendable*: drain this one first so the accounts worth keeping stay full. A pin says
the reverse — this account, whatever its pressure. Overloading one field with both
intents makes every future ranking decision ambiguous, so `pinned` is a separate value.

## Where the override is applied

Three places, each chosen so the pin skips *preference* and never skips *capability*:

1. **The pace-gate filter**, exempting a pinned account. A pace gate is an operator
   promise about someone else's quota; pinning is the same operator withdrawing it for
   one account, deliberately.
2. **After the availability loop and the backoff-fallback path**, narrowing `available`
   to the pinned account. Placing it there means the pin inherits every hard filter
   above it and overrides every ranking stage below it — including the health-tier
   collapse, which happens immediately after.
3. **`_select_account_preferring_budget_safe`**, which has its own health-tier collapse
   and would otherwise never reach the pinned account. It tries the pin first and falls
   through when the pin yields nothing.

Session stickiness is handled at its own site: a sticky mapping that names a different
account is ignored while a pin is in force.

## Release, not clearing

"Until the account is full, then automatic again" has an ambiguity worth naming: does an
exhausted pin *clear* or *pause*? It pauses. A five-hour window refills; clearing the pin
on exhaustion would mean the operator has to re-pin after every window, and the state
they set would be erased by an event they did not cause. So the pin is durable and only
its *effect* lapses, for exactly as long as the account cannot serve.

The release condition is deliberately "cannot serve" rather than "is out of quota",
because the failure modes an operator cares about are the same either way: a paused,
rate-limited, re-auth-needed, or hard-erroring account cannot carry traffic, and stalling
the pool on a pin would be worse than routing around it.

## What the pin still cannot do

- It cannot make an account serve a model it is not entitled to, or draw on an
  additional quota pool it has none of.
- It cannot escape an API key's account scope: the relay hands the selector a
  pre-scoped list, and a pin outside that list is simply not present.
- It cannot revive a `reauth_required` or `deactivated` account.

## Worked example

Two Claude seats, `A` pinned and `B` normal. `A` has `pace_margin_primary_pct = 20` and
sits at 27% of its five-hour window against an even-pace line of 26.7%; `B` sits at 4%.

- Before: `A` fails the primary pace gate, never reaches the ranking stage, and `B`
  serves every request while the UI shows `A` marked.
- After: `A` is exempt from the gate, is the only candidate, and serves. When `A` hits
  `quota_exceeded`, `B` serves until `A`'s window resets, and then `A` resumes — with no
  operator action at either transition.

# Pace Gates

Pace gates limit *how fast* an account may be drawn from, rather than how much of it may be used.
They exist for pooled accounts that someone else also depends on: the gate keeps the pool from
consuming a window faster than its owner would.

All three gates are per-account and unset by default. An installation that never configures them
behaves exactly as it did before.

## The even-pace line

Each quota window has an even-pace line — the usage the account would show if the window's quota
were spent at a constant rate:

```
expected % = 100 × elapsed / window length
```

Two hours into a five-hour window, the line sits at 40%. Six days into a weekly window, it sits at
about 86%. Usage below the line is behind schedule; usage above it is ahead.

A pace gate is a margin below that line. With a margin of 20, the account is only selectable while
its usage is at least 20 points *below* the line — at the midpoint of a weekly window that means
30% or less. A margin of 0 gates exactly at the line.

## The three gates

| Gate | Effect |
|---|---|
| `paceMarginPrimaryPct` | Selectable only while short-window (5h) usage is this many points below the 5h pace line. |
| `paceMarginSecondaryPct` | Selectable only while weekly usage is this many points below the weekly pace line. |
| `preResetWindowMinutes` | Selectable only within this many minutes of the short-window reset. |

Margins accept `0`–`100`; the window accepts any non-negative number of minutes.

## Combining gates

Gates combine with AND — the account must satisfy every configured gate. To express *"only in the
two hours before the 5h reset, only below the 5h pace line, and only 20 points below the weekly
line"*:

```bash
curl -X PUT https://your-proxy/api/accounts/<account-id>/pace-gates \
  -H 'Content-Type: application/json' \
  --cookie "$DASHBOARD_SESSION" \
  -d '{
        "preResetWindowMinutes": 120,
        "paceMarginPrimaryPct": 0,
        "paceMarginSecondaryPct": 20
      }'
```

Omitting a field leaves that gate as it is. Sending an explicit `null` clears it.

## How gates interact with everything else

- **Gates are hard filters.** A gated-out account is removed from the selection pool before any
  ranking runs, so no later tier can re-admit it — including `burn_first`, budget-safe fallback, and
  backoff fallback. If every candidate is gated out, the request fails with an error naming pace
  gating rather than quietly using a gated account.
- **Gates are not a quota cap.** They shape the *rate* of consumption. The existing budget
  thresholds, routing policy, and account status all still apply.
- **A gate needs window bounds to act.** If the reset timestamp or window length for a window is
  unknown, that gate does not apply. This matters for a freshly imported account: window data
  arrives with served traffic, so a newly added account is not gated until it has reported usage.
  Treating unknown bounds as a failure would strand such an account permanently.
- **Usage is read as the router sees it**, which includes a small in-flight pressure term used to
  spread concurrent requests. The effect is a fraction of a point per in-flight request and biases
  gates very slightly toward holding back, which is the conservative direction for their purpose.

## Choosing between a gate and a routing policy

`preserve` holds an account back as a fallback of last resort; `burn_first` drains it as fast as
possible. Pace gates sit between the two: the account carries normal traffic, but only while it is
running behind schedule. Use a policy when you want to change an account's *rank*, and a gate when
you want to bound its *rate*.

---

*Spec: [account-routing](https://github.com/Soju06/codex-lb/tree/main/openspec/specs/account-routing)*

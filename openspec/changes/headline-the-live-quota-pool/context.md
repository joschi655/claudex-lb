# Context

## The two pools, and why order matters

Anthropic reports a usage-based seat's dollars in two places, and the poller
persists them as two separate usage windows (`budget` and `extra_credits`):

| Field on `AccountSummary` | Source | What it is |
|---|---|---|
| `spendBudget` | the payload bucket carrying `limit_dollars` | the plan's own allowance for the period, with a `resetAt` |
| `extraCredits` | `spend`, gated on `extra_usage.is_enabled` | the top-up pool that keeps the seat serving past that allowance |

They are consumed in that order, which is why the live seat that motivated this
change reads the way it does: the plan budget at $1000 of $1000 and the
extra-usage pool already $84.86 into its $200. The plan budget ran out and
spending moved to the pool behind it. Reading only the first of the two reports
that seat as spent while it has $115.14 left and is a candidate for the next
request.

The order also settles what "live" means. It is not "the larger pool" or "the
one with the most left" — it is the one currently being drawn down, which is the
first one that still has headroom.

## Why the extra-usage pool must be enabled to count

`extraCredits` is reported even when the facility is switched off, deliberately:
a disabled pool is the state an operator acts on, so
`show-anthropic-extra-credits` made it render rather than vanish. That makes
`enabled` load-bearing here. A disabled pool with a limit and a remainder still
describes money the seat cannot spend, and selecting it as live would report
headroom on a seat that has none.

## Why exhaustion drops out of the menu-bar title

`menuBarTitle` already falls back to the pool's least-used window when the next
account reports no figure of its own. Today a spent budget defeats that fallback
by returning a number — `100%` — which is a true statement about a pool nobody
can spend from, presented where the reader expects "how much room is there". A
spent seat now returns nothing, so the existing fallback runs and the title
reports a window that still means something.

This is presentation only. Routing, pace gates, and the pin are untouched, and
`fail-over-on-extra-usage-exhaustion` already handles what happens when a drained
seat is actually asked to serve: the `400` naming spent usage is classified as
exhaustion and the relay moves on.

## The overview endpoint never carried the pools

Found by asking the live deployment rather than reading the mapper. The same
account, at the same moment, over two endpoints:

```
GET /api/accounts          -> spendBudget {usedPercent 100, limit 1000, remaining 0}
                              extraCredits {enabled true, usedPercent 42.43, remaining 115.14}
GET /api/dashboard/overview -> spendBudget null
                               extraCredits null
```

`DashboardService.get_overview` loads `primary`, `secondary`, and `monthly` and
calls `build_account_summaries` without `budget_usage` or `extra_credits_usage`;
the mapper defaults both to `None` and maps them to `null`. `AccountsService`
loads all five. The response schema already declares the fields — nothing was
missing from the contract, only from the query.

This is the load-bearing half of the dashboard fix. Correcting the components
alone would have moved the seat from two empty window bars to "No budget
reported yet", which is a different wrong answer about an account whose budget
the server has stored.

`get_projections` is deliberately left alone: it builds summaries only to feed
`build_weekly_credit_pace`, which reads window credits. Loading dollar pools
there would cost two queries per poll to populate fields nobody reads.

## Why the dashboard page was missing this entirely

`declare-account-quota-kind` unified the accounts page's two surfaces — the list
row and the detail panel — onto `resolveQuotaKind`, because they had inferred
separately and disagreed. The dashboard page's card and list were not part of
that change and still branch on `windowMinutesPrimary` / `windowMinutesSecondary`
directly. For a seat that reports neither, every branch falls through to the
two-column 5h + weekly layout, and both bars render at 0 with no reset label and
no dollar figure. Adding a third and fourth independent inference is what
`resolveQuotaKind` exists to stop, so both call it.

## Failure modes considered

- **Utilization above 100%.** A pool over its limit reports utilization above
  100. Remaining percentage is clamped at 0 rather than rendering negative, and
  "has headroom" is `utilization < 100`, so an over-limit pool is correctly not
  live.
- **A pool with a percentage but no amounts.** `usedPercent` is always present on
  a persisted row; `limit` and `remaining` are nullable. The presentation falls
  back to the percentage alone rather than rendering an empty amount.
- **A subscription seat that also reports a budget.** Unchanged: it keeps its
  window bars, and the detail panel keeps showing the budget beneath them.

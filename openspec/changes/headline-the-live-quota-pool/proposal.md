## Why

A usage-based seat bills against two dollar pools, not one. The plan's own
allowance is spent first; the extra-usage pool behind it is what keeps the seat
serving once that allowance is gone — and it is the pool Anthropic names when a
seat finally runs dry ("You're out of extra usage"). Every compact quota surface
reads only the first of the two, so a seat is reported as spent while it still
has money to spend.

A live enterprise seat shows exactly this. Its plan budget reads $1000 of $1000,
100% used; its extra-usage pool reads $84.86 of $200, with $115.14 left. The
account list row renders `0% left · $0.00`, and the menu bar would headline
`100%` the moment the pool routed to it. Both are wrong about the same seat at
the same moment: it has 58% of its live pool remaining and is the account that
would serve.

The dashboard page is worse than wrong, it is silent, and for two reasons at
once. `AccountCard` and `AccountList` draw 5h and weekly bars unconditionally,
and a usage-based seat reports neither window — so that seat renders two empty
bars and no dollar figure anywhere, the one presentation the quota-kind setting
exists to prevent, still in place on the surface an operator opens first.

Underneath it, `GET /api/dashboard/overview` has no pools to give them. It loads
the three window kinds and stops, while `GET /api/accounts` also loads the
`budget` and `extra_credits` rows. The same seat therefore arrives at the two
pages carrying different data: `spendBudget` populated on one and `null` on the
other. Fixing only the components would have left them rendering "No budget
reported yet" for an account whose budget the server knows perfectly well.

## What Changes

- A usage-based account presents its **live pool**: the first of the plan budget
  and the extra-usage pool that still has headroom. A spent plan budget hands
  off to the extra-usage pool rather than standing in for it.
- When neither pool has headroom, the seat presents as spent rather than
  silently picking one, and the menu-bar title stops reporting that seat's
  figure at all — it falls back to the pool's least-used window, as it already
  does for a seat with no data.
- `GET /api/dashboard/overview` loads the `budget` and `extra_credits` usage
  rows alongside the three window kinds, so an account describes itself the same
  way on both pages. The fields already exist on the response schema; they were
  simply never populated.
- The dashboard page's account card and account list present usage-based seats
  through the same resolver the accounts page uses, so a usage-based seat shows
  its pool instead of two empty window bars.
- The account detail panel is unchanged: it already shows both pools in full,
  which is what a detail panel is for. Only the compact surfaces — where exactly
  one figure fits — gain the notion of which pool is live.

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `account-quota-presentation`: which dollar pool a usage-based account presents
  becomes a resolved property of the account rather than "whichever pool the
  surface happened to read first", and the dashboard page's quota surfaces join
  the accounts page in honouring the resolved quota kind.

## Impact

- Server: `app/modules/dashboard/service.py` loads two more usage windows in
  `get_overview` and passes them to the mapper it already calls. Two extra
  `latest_by_account` reads per overview, the same two the accounts endpoint
  makes. `get_projections` is untouched — it builds summaries only for the
  weekly pace calculation, which is window-based.
- Frontend: `frontend/src/features/accounts/quota-kind.ts` gains
  `resolveLiveQuotaPool`; `frontend/src/features/accounts/components/account-list-item.tsx`,
  `frontend/src/features/dashboard/components/account-card.tsx`, and
  `frontend/src/features/dashboard/components/account-list.tsx` call it.
- Menu bar: `scripts/swiftbar/claudex-lb.1m.ts` mirrors the same rule in
  `badge()` and `usedPercent()`.
- Tests: `tests/integration/test_dashboard_overview_usage_based_pools.py`,
  `frontend/src/features/accounts/quota-kind.test.ts`,
  `frontend/src/features/dashboard/components/account-card.test.tsx`,
  `frontend/src/features/dashboard/components/account-list.test.tsx`,
  `frontend/src/features/accounts/components/account-list-item.test.tsx`.
- Specs: `openspec/specs/account-quota-presentation/spec.md`.
- No schema change and no migration: both pools are already polled, persisted,
  and carried on `AccountSummary`. The response schema already declares the
  fields; only one endpoint failed to fill them.

## Simplicity

No new `CODEX_LB_*` setting and nothing to configure. The rule is derived from
the data the account already reports, and an account with one pool or none
renders exactly as it does today. One resolver serves all four surfaces rather
than four separate inferences — the same shape, and the same reason, as
`resolveQuotaKind`, which exists because two surfaces inferring separately
disagreed about a live account.

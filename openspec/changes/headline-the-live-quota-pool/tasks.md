# Tasks

## 0. Server

- [x] 0.1 `DashboardService.get_overview` loads the `budget` and `extra_credits`
      usage windows and passes them to `build_account_summaries`, so an account
      describes itself identically on both pages. `get_projections` stays as it
      is — it builds summaries only for the window-based weekly pace.
- [x] 0.2 `tests/integration/test_dashboard_overview_usage_based_pools.py`:
      both pools reach the overview, the two endpoints agree on them, and a
      subscription seat still reports neither.

## 1. Resolver

- [x] 1.1 Add `resolveLiveQuotaPool(account)` to
      `frontend/src/features/accounts/quota-kind.ts`, returning the live pool
      (kind, label, remaining percentage, remaining and limit amounts, currency,
      reset) or `null` when the account reports no pool at all.
- [x] 1.2 Select the plan budget when it has headroom, the extra-usage pool when
      it is enabled and has headroom, and otherwise the spent state — preferring
      the enabled pool, since that is the one an exhausted seat is out of.
- [x] 1.3 Clamp remaining percentage to `[0, 100]` so an over-limit pool reads 0
      rather than negative.
- [x] 1.4 Cover the resolver in `quota-kind.test.ts`: handoff on a spent budget,
      budget preferred while it has headroom, a disabled pool never selected,
      both pools spent, no pool at all, and amounts absent.

## 2. Accounts page list row

- [x] 2.1 Point `MiniBudgetRow` in `account-list-item.tsx` at the resolved live
      pool and label the row by the pool it is showing.
- [x] 2.2 Extend `account-list-item.test.tsx`: a seat with a spent budget and a
      live extra-usage pool shows the pool's remaining percentage and amount,
      and a switched-off pool is never selected.

## 3. Dashboard page

- [x] 3.1 `account-card.tsx`: resolve the quota kind, and for a usage-based
      account render the live pool in place of the 5h/weekly bars.
- [x] 3.2 `account-list.tsx`: same in `accountQuotaLabels`, so the quota cell and
      the quota sort both read the live pool rather than absent windows.
- [x] 3.3 Tests in `account-card.test.tsx` and `account-list.test.tsx`: a
      usage-based seat renders its pool and renders no 5h/weekly bar; a
      subscription seat is unchanged.

## 4. Menu bar

- [x] 4.1 Mirror the resolver in `scripts/swiftbar/claudex-lb.1m.ts` and extend
      the plugin's `Account` interface with `extraCredits`.
- [x] 4.2 `badge()` shows the live pool; `usedPercent()` returns `null` for a
      seat whose pools are all spent, so `menuBarTitle` falls through to the
      pool's least-used window.
- [x] 4.3 Show the extra-usage pool in the section detail only when it carries
      something — money moving through it, or a spent budget the operator could
      turn it on for. Every seat reports the pool, most of them off and empty.
- [x] 4.4 Honour `quotaKind` in the plugin as the web surfaces do, so a seat
      declared usage-based follows its pool in the menu bar too rather than a
      stale window figure.

## 6. Review findings

- [x] 6.1 A pool with no reported limit is not evidence of headroom. The poller
      records `used_percent = 0` there; reading it as an untouched pool painted a
      full bar over a seat whose overflow state is unknown, and would have made
      the menu-bar title report the whole section as fresh.
- [x] 6.2 The asymmetry between the two pools is deliberate and encoded: a plan
      budget's utilization is always real, the extra-usage pool's is a derived
      figure with a zero sentinel.
- [x] 6.3 Reconcile the delta with the sibling `show-anthropic-extra-credits`
      requirement, which states the pool is presented alongside rather than in
      place of the existing surface — scoped explicitly to compact surfaces so a
      reviewer merging deltas does not read a contradiction.

## 5. Verify

- [x] 5.1 `cd frontend && bun run test` (127 files, 915 tests), `bun run lint`,
      and `bun run typecheck` all clean.
- [x] 5.2 `uv run pytest`: 4179 passed across `tests/unit` plus the dashboard,
      overview-pool, and quota-kind integration suites. The full-suite run showed
      one unrelated `test_multi_replica` leader-election timeout, which passes in
      isolation and ran before this change was in place.
- [x] 5.3 `openspec validate --specs` and `validate headline-the-live-quota-pool
      --strict`.
- [x] 5.4 Ran the plugin against the live deployment: the enterprise seat's row
      moved from `0% left · $0.00` to `58% left · $115.14`.
- [ ] 5.5 Before/after screenshots of the dashboard page for the PR body
      (dashboard-visible change).

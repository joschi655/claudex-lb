## Why

The dashboard can say whether an account *may* serve and never whether it *is*.
`StatusBadge` has six values — `active`, `paused`, `limited`, `exceeded`,
`reauth`, `deactivated` — and every one of them answers the eligibility
question. The load balancer does track which account it last picked, in
`RuntimeState.last_selected_at`, but that lives in one process's memory: it is
never persisted and never returned by the accounts API. So an operator watching
four active Claude accounts cannot tell which one is carrying the traffic, for
either provider.

The same page has the mirror-image gap on the way in. Pace gates decide
eligibility more often than status does — an account can be `active`, healthy,
and completely excluded because its usage sits above the pace line or its 5h
reset is outside the pre-reset window. The API has accepted all three gates
since they landed, and the account summary already returns them, but nothing in
the dashboard renders or edits them. Setting one has meant the menu bar or a
`curl`, and diagnosing a silent exclusion has meant reading the database.

Together those gaps produce the failure operators actually hit: an account is
marked in the UI, is excluded by a gate the UI does not show, and the traffic
goes somewhere the UI does not name.

## What Changes

- The account summary reports `lastServedAt` — when an account most recently
  carried a request, within a recent window. Absent means "not recently", which
  is the answer an idle pool should give.
- The account list renders a `Serving` badge on the account whose request is
  newest within its provider, in place of its status badge. Claude and Codex are
  scored separately, so each names its own.
- The account actions panel gains inputs for the three pace gates
  (`paceMarginPrimaryPct`, `paceMarginSecondaryPct`, `preResetWindowMinutes`),
  each committing on blur and clearable by emptying the field.

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `account-routing`: per-account recent serving activity is reported on the
  account summary, and the pace gates become editable from the dashboard.
- `account-quota-presentation`: the account list distinguishes the account that
  is serving from the accounts that merely could.

## Impact

- Code: `app/modules/accounts/{repository,mappers,schemas,service}.py`
- Frontend: `frontend/src/features/accounts/{schemas.ts,api.ts,serving.ts,hooks/use-accounts.ts,components/{account-list,account-list-item,account-actions,account-detail,accounts-page,pace-gate-fields}.tsx}`
- Migration: none. The serving signal is derived from `request_logs`, and the
  gate columns already exist.
- Tests: `tests/unit/test_accounts_last_served.py`,
  `tests/integration/test_accounts_api_routing_policy.py`,
  `frontend/src/features/accounts/serving.test.ts`
- Specs: `openspec/specs/account-routing/spec.md`,
  `openspec/specs/account-quota-presentation/spec.md`

## Simplicity

No new `CODEX_LB_*` setting: the freshness window is a display decision with one
defensible value, not a knob. No new endpoint — the gates use the `PUT
/api/accounts/{id}/pace-gates` route that already exists, and the serving signal
rides the account listing that the page already loads, so the dashboard makes no
extra request. No new dashboard nav item; both changes render inside surfaces
that are already there.

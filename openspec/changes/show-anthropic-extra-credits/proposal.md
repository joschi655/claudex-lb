## Why

`/api/oauth/usage` reports an `extra_usage` block for Claude accounts — the top-up pool
that covers spend past the plan's own limits — and `parse_usage_payload` has parsed it
into `AnthropicExtraCredits` since the poller landed. Nothing then does anything with it:
`persist_usage_api_snapshot` writes the five-hour, weekly and budget windows and drops
the pool on the floor. It is parsed, unit-tested, and invisible.

That matters most exactly when an operator is looking. Once a seat's windows are spent,
the extra-usage pool is the only headroom it has left, so it decides whether the account
can still serve at all. Today the dashboard shows a fully-spent seat with no indication
that it has $184 of overflow available, or that the facility exists but is switched off
and could be turned on. `fail-over-on-extra-usage-exhaustion` already routes on the
consequence of this pool being empty; this change makes the pool itself legible.

Reporting a *disabled* pool is deliberate. "Off" is the state an operator acts on — it is
the difference between "this account is out of options" and "this account could keep
serving if you enabled overflow".

## What Changes

- `persist_usage_api_snapshot` writes an `extra_credits` usage window whenever the payload
  reports the facility, enabled or not. `credits_has` carries the on/off state,
  `credits_limit` the pool size, `credits_balance` the remainder; the amount spent is
  derived from those two rather than stored a third time.
- `AnthropicUsageApiSnapshot.has_any` and the poller's unchanged-write fingerprint both
  learn about extra credits. Without the first, a payload that reports *only* a pool is
  treated as an empty snapshot and never written; without the second, overflow spend that
  moves while the windows sit still is deduplicated away and the figure goes stale.
- `AccountSummary` gains an `extra_credits` object (`enabled`, `used_percent`, `used`,
  `limit`, `remaining`, `currency`), fed from the newest `extra_credits` row.
- The dashboard account usage panel renders the pool: a spend bar and the
  spent-of-limit/remaining amounts when enabled, an explicit "Off" state when not.

No new settings and no schema migration — the `extra_credits` window reuses the existing
credit columns on `usage_history`, the same ones the budget window already uses.

Out of scope: **enabling** extra usage from the dashboard. The endpoints exist
(`PUT /api/oauth/organizations/{orgUUID}/overage_spend_limit`, plus a one-time
`setup_overage_billing`), but authorizing real overflow spend needs its own change with an
explicit confirmation step. This change only makes the state visible.

## Capabilities

### Modified Capabilities

- `anthropic-provider`: usage ingestion MUST persist the extra-usage pool, including when
  it is disabled.
- `account-quota-presentation`: an account that reports an extra-usage pool MUST present
  it alongside whatever quota surface it already has.

## Impact

`app/core/anthropic/usage_ingest.py`, `app/core/anthropic/usage_api.py`,
`app/core/anthropic/usage_poller.py`, `app/modules/accounts/{schemas,mappers,service}.py`,
`frontend/src/features/accounts/{schemas.ts,components/account-usage-panel.tsx}`.
Accounts that report no pool are unaffected — the field is absent and the row renders
exactly as before.

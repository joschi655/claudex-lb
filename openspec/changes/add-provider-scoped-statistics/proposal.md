## Why

With the Anthropic relay now writing request logs, one pool serves two providers and
every statistic mixes them. `request_logs` has no provider dimension at all: the request
list, its filter facets, and the daily reports aggregate Claude and Codex rows into single
numbers. That makes the aggregates misleading rather than merely coarse — a cost-per-day
chart averages rows that have a price against rows that never can, tokens-per-day sums
counters produced by two different tokenizers, and a model donut lists `gpt-5.6-sol` next
to `claude-sonnet-4-5` as if they competed for the same capacity. They do not: they draw
on separate quotas, refill on separate schedules, and fail in separate ways.

Filtering by account is the only separation available today, and it does not survive
contact with the pool. Accounts come and go, `request_logs.account_id` is `ON DELETE SET
NULL`, and reconstructing "which of these ids were the Claude ones" by hand is exactly the
work the dashboard exists to avoid.

## What Changes

- `request_logs` gains a `provider` column, denormalized from the serving account at write
  time — the same treatment `plan_type` already gets, and for the same reason: the account
  row can be deleted out from under the log.
- Existing rows are backfilled from their account where one still exists, and default to
  `openai` otherwise, so historical statistics keep the meaning they had.
- The request-log list accepts a `provider` filter, returns the provider on each row, and
  reports the available providers among its filter options.
- The daily reports endpoint accepts the same `provider` filter, so cost, token, latency,
  and distribution charts can be read one provider at a time.
- The dashboard's request list and reports page each gain a provider control. Neither
  defaults to a provider: an unfiltered view is still the whole pool, exactly as today.

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `proxy-runtime-observability`: request-log rows gain persisted provider metadata, and
  the statistics surfaces gain provider-scoped filtering.

## Impact

- Schema: new nullable `request_logs.provider` column with an index, plus a backfill.
- Code: `app/db/models.py`, `app/modules/request_logs/{repository,service,schemas,api}.py`,
  `app/modules/reports/{repository,service,api}.py`.
- Frontend: request-log filter bar and row rendering, reports filter bar.
- Migration: one revision on top of `20260804_000000_add_account_pace_gates`.
- Tests: request-log repository/API filtering, reports filtering, migration backfill, and
  the frontend filter components.

## Simplicity

No new `CODEX_LB_*` settings. The feature is zero-config and additive: with no provider
selected every surface behaves exactly as it does today, so a single-provider pool never
sees the control do anything. No new dashboard nav item — the filter lives inside the two
pages that already exist. Provider is stored as the same plain string the accounts table
already uses, so no enum, mapping table, or new vocabulary is introduced.

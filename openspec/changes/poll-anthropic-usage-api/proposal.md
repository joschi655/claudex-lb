## Why

A Claude account's quota state only ever reaches the proxy on the back of a request it
served. `parse_unified_usage` reads the `anthropic-ratelimit-unified-*` headers off a
relayed response, and `_ordered_usage_refresh_accounts` filters Anthropic rows out of the
poll loop entirely. So an account the pool is not currently using has no way to tell the
pool anything, and its last sample stands in for the truth however old or however wrong
it is.

Observed in production on 2026-08-05: one account's stored five-hour utilization read
1.06% while the account was in fact fully spent. Its own history shows the sequence —
44%, 60%, 75%, 91%, then a single `1.06%` sample at 09:59:11 — after which the account
stopped serving traffic and the number froze. The load balancer reads that row as
"98% free" and will keep selecting an account that can only answer 429.

Two things had to both be true for that to happen, and this change fixes the second:

1. A response reported a five-hour utilization far below the preceding samples. Header
   ingestion has no way to reject it — it holds one sample per window and no history to
   judge it against.
2. Nothing ever looked again. With no poll, a wrong sample is permanent until traffic
   happens to return to that account.

The same gap hides usage-based seats completely. An enterprise seat billing against a
dollar budget reports `five_hour: null` and `seven_day: null`, so no window row is ever
written and the dashboard shows the account with no quota information at all — while its
budget is in fact 77.7% spent.

`add-anthropic-limit-warmup` asserted that "Anthropic publishes no usage API to poll".
That is not correct. `GET https://api.anthropic.com/api/oauth/usage` answers for an OAuth
subscription credential with the `oauth-2025-04-20` beta flag, and returns both the
window utilizations and the dollar-denominated buckets. This change consumes it and
supersedes that claim.

## What Changes

- A usage-API client polls `GET /api/oauth/usage` per Anthropic OAuth account on the
  existing usage-refresh cadence, writing primary and secondary window rows through the
  same `persist_usage_snapshot` contract header ingestion already uses. An idle account
  therefore converges on the truth without having to serve a request first.
- The poll is authoritative for the windows it reports: it replaces the stored sample
  rather than merging with it, which is what corrects a poisoned row.
- Dollar-denominated buckets are recorded as a new `budget` usage window. The bucket key
  is not hardcoded — the payload names these buckets with rotating code words
  (`cinder_cove`, `tangelo`, `nimbus_quill`, …), so any top-level object carrying a
  non-null `limit_dollars` is treated as the budget.
- `AccountSummary` gains a spend block (used, limit, remaining, currency, reset, plus the
  extra-usage credit figures when enabled), and the dashboard renders a spend bar for
  accounts that report a budget instead of a five-hour window. This is what makes a
  usage-based seat legible at all.
- Static API-key credentials are skipped: the endpoint is OAuth-scoped and a console key
  has no subscription state to report.
- HTTP 429 from the endpoint puts that account's poll in a cooldown. The endpoint
  throttles aggressively and Claude Code polls it too, so a 429 is expected traffic
  shaping, not an account fault: it changes no account status and is not logged as an
  error.

## Capabilities

### Modified Capabilities

- `anthropic-provider` — usage state is polled from Anthropic's usage API in addition to
  being ingested from served-response headers, and usage-based seats expose a spend
  budget.
- `account-quota-presentation` — an account whose quota is a dollar budget presents that
  budget where a window-based account presents its windows.

## Impact

- No database migration. `usage_history.window` is a free-form string; `budget` is a new
  value in that column, and the existing `credits_*` columns carry the dollar figures.
- Adds one outbound call per Anthropic account per refresh interval, subject to the
  cooldown. No new setting: the poll follows `CODEX_LB_USAGE_REFRESH_ENABLED` and
  `CODEX_LB_USAGE_REFRESH_INTERVAL_SECONDS`, which already govern the loop it runs in.
- Corrects a routing hazard: the selector stops trusting an indefinitely stale sample for
  an idle account.

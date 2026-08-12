## Why

Claude requests are logged with tokens but no price. Every Anthropic row in
`request_logs` carries `cost_usd = NULL`, because `DEFAULT_PRICING_MODELS` holds
only `gpt-*` entries and `get_pricing_for_model` returns nothing for a
`claude-*` model. The cost column, the cost-per-day chart, and the per-account
cost donut therefore report Claude traffic as free, while the same views price
Codex traffic to the cent. On the deployment that prompted this, that is 6,783
requests and roughly 1.15 billion input tokens showing as $0.

Pricing them needs one thing the schema does not currently keep. Anthropic bills
three input counters at three different rates — uncached input at the base rate,
cache reads at 0.1x, and cache writes at 1.25x (5-minute TTL). The relay
currently folds all three into `input_tokens` and keeps only the cache reads
separately, so a cache write is indistinguishable from uncached input once
stored and is necessarily priced at the base rate. On Claude Code traffic, where
89% of input tokens are cache reads and most of the remainder is cache writes,
that under-reports the bill by roughly 10%.

## What Changes

- Claude models enter the pricing table at their published rates, with cache
  reads priced through the existing `cached_input_per_1m` field. Snapshot
  aliases (`claude-haiku-4-5-20251001`) resolve to the canonical entry.
- `ModelPrice` gains `cache_write_per_1m` and `UsageTokens` gains
  `cache_write_input_tokens`. A model that does not set the rate prices cache
  writes at its base input rate, so no OpenAI cost changes.
- The relay stops discarding `cache_creation_input_tokens` and records it in a
  new `request_logs.cache_write_input_tokens` column. `input_tokens` keeps its
  current meaning as the total, so existing readers are unaffected.
- The cost breakdown gains a `cacheWriteUsd` component, and the request-log
  tooltip gains the matching segment, so the parts continue to sum to the total.
- The migration backfills `cost_usd` for existing Anthropic rows from their
  stored tokens, so historical Claude usage stops reading as free.

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `api-keys`: request cost accounting recognizes Claude model pricing, and
  prices cache-write tokens at their own published rate rather than at the base
  input rate.
- `anthropic-provider`: the relay records cache-write tokens as their own
  counter in addition to the total-and-subset columns it already writes.

## Impact

- Code: `app/core/usage/pricing.py`, `app/core/usage/logs.py`,
  `app/core/anthropic/messages_usage.py`,
  `app/modules/anthropic_proxy/service.py`,
  `app/modules/request_logs/{repository,schemas,mappers}.py`,
  `app/db/models.py`
- Migration: `20260812_000000_add_request_log_cache_write_tokens` — adds the
  column and backfills `cost_usd` on Anthropic rows that have none.
- Frontend: `frontend/src/features/dashboard/schemas.ts`,
  `frontend/src/features/dashboard/components/recent-requests-table.tsx`
- Tests: `tests/unit/test_pricing.py`,
  `tests/unit/test_anthropic_messages_usage.py`,
  `tests/integration/test_request_log_claude_cost.py`,
  `frontend/src/features/dashboard/**/*.test.{ts,tsx}`
- Specs: `openspec/specs/api-keys/spec.md`, and the `anthropic-provider`
  capability once `add-anthropic-request-logs` is synced.

## Simplicity

No new `CODEX_LB_*` setting: prices are a published fact, not an operator
preference, and the existing table is already a code constant. The cache-write
rate is optional on `ModelPrice`, so every existing entry keeps its current
behaviour without being touched. No new README section — the rate table is
documented alongside the capability.

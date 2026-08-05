## Why

The Anthropic relay serves traffic but records nothing in `request_logs`. Every row in
that table is Codex traffic, so a pool that mixes Claude and Codex accounts reports on
only half of itself: the dashboard's request list, the reports pages, per-account token
and latency statistics, and the API-key attribution surfaces all show Claude accounts as
permanently idle no matter how much they serve.

The gap is not a missing table or schema — `request_logs` already carries every column
the relay would need. It is simply that the relay's response path was written as a pure
pass-through and never grew a log write. Until it does, no statistics work downstream of
it can be built, because there is no data to aggregate.

## What Changes

- The Anthropic relay records exactly one `request_logs` row per upstream attempt against
  a selected account: account id, API key id, model, status, error code, upstream status
  code, total latency, and — for streaming responses — time to first byte.
- Token usage is extracted from the Messages API response: from the JSON body for
  non-streaming responses, and from the `message_start` / `message_delta` SSE events for
  streaming ones, without buffering the response or delaying a single byte to the client.
- Anthropic's split input counters are normalized to the columns' existing meaning:
  `input_tokens` becomes the **total** prompt size (uncached + cache reads + cache
  writes) and `cached_input_tokens` the cache-read portion, because the cost path already
  treats cached tokens as a subset of input.
- A failover sequence produces one row per attempted account, so an account that 429s and
  hands off is visible as a failed attempt rather than vanishing behind the account that
  eventually served the request.
- `POST /v1/messages/count_tokens` is deliberately **not** logged: it consumes no quota,
  produces no completion, and Claude Code issues it often enough that logging it would
  distort every per-request statistic against the Codex baseline.
- `cost_usd` is left NULL for Claude models rather than synthesized from list prices,
  because these are subscription seats whose marginal per-request cost is zero.

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `anthropic-provider`: the relay gains request-log emission as part of its documented
  behavior, alongside the existing usage-header ingestion.

## Impact

- Code: `app/modules/anthropic_proxy/service.py`, `app/modules/anthropic_proxy/api.py`,
  new `app/core/anthropic/messages_usage.py`; `_request_log_useragent_fields` moves from
  `app/modules/proxy/_service/support.py` to `app/core/usage/useragent.py` so both proxies
  share one implementation.
- Migration: none. `request_logs` already has every column used.
- Tests: new `tests/unit/test_anthropic_messages_usage.py`,
  `tests/integration/test_anthropic_request_logs.py`.
- Specs: `openspec/changes/add-anthropic-provider/specs/anthropic-provider/spec.md`
  (that capability is still an unarchived change; these requirements are additive to it).

## Simplicity

No new `CODEX_LB_*` settings and no new schema. Logging is unconditional for relayed
completions, matching the OpenAI path, so there is no toggle to reason about. The write
happens on a tracked background task off the response path, so the feature cannot add
latency to a served request, and a logging failure is swallowed with a warning rather
than surfaced to the client.

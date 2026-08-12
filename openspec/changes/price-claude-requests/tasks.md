# Tasks

## 1. Pricing gains a third input rate

- [ ] 1.1 `ModelPrice.cache_write_per_1m`, defaulting to `None` so every
      existing entry keeps its current behaviour
- [ ] 1.2 `UsageTokens.cache_write_input_tokens`, and `_normalize_usage` clamps
      the two cache counters so together they never exceed the total input
- [ ] 1.3 `_effective_rates` returns a cache-write rate alongside the others,
      falling back to the base input rate when the model states none
- [ ] 1.4 `calculate_cost_breakdown_from_usage` charges the three input parts
      separately; `UsageCostBreakdown.cache_write_usd`

## 2. Claude enters the price table

- [ ] 2.1 Entries for Fable 5, Opus 5/4.8/4.7/4.6/4.5, Sonnet 5/4.6/4.5,
      Haiku 4.5 at their published rates, with no long-context threshold
- [ ] 2.2 Aliases so snapshot-dated identifiers resolve to the family entry,
      with the longer pattern winning where two would match

## 3. The relay keeps the counter

- [ ] 3.1 `AnthropicMessageUsage.cache_write_input_tokens` — stop discarding
      `cache_creation_input_tokens` after using it in the total
- [ ] 3.2 The SSE accumulator merges it like the other input counters, so a
      later event that omits it does not erase it
- [ ] 3.3 `_PendingRequestLog` and `_record_success` carry it to the log write

## 4. Storage

- [ ] 4.1 `RequestLog.cache_write_input_tokens`, nullable
- [ ] 4.2 Migration `20260812_000000_add_request_log_cache_write_tokens`: add the
      column, then backfill `cost_usd` on Anthropic rows that have none, with
      the rates written as literals rather than imported
- [ ] 4.3 `add_log` accepts and stores it
- [ ] 4.4 `RequestLogLike` and `usage_tokens_from_log` read it, so both the
      write-time and read-time cost paths see the same three parts

## 5. Presentation

- [ ] 5.1 `cache_write_usd` through the request-log schema and mapper
- [ ] 5.2 The tooltip gains a cache-write segment, so the segments still sum to
      the total

## 6. Tests

- [x] 6.1 `tests/unit/test_pricing.py` — the three input parts are charged once
      each at their own rates; a model without a cache-write rate is unchanged;
      Claude models and their snapshot aliases resolve
- [x] 6.2 `tests/unit/test_anthropic_messages_usage.py` — the counter survives
      both the buffered and the streamed shape, and stays absent when unreported
- [x] 6.3 `tests/integration/test_anthropic_request_logs.py` — a relayed Claude
      request lands a row with a non-null `cost_usd` and the counter set. Folded
      into the existing relay test, whose `cost_usd is None` assertion was the
      thing this change reverses
- [x] 6.4 `tests/integration/test_request_log_cache_write_migration.py` — the
      backfill prices existing rows, is re-runnable, and agrees with the
      application's own cost path (they must, or the mapper drops the breakdown)
- [x] 6.5 Frontend: the breakdown renders the cache-write segment, and omits it
      for a row that recorded none

## 7. Verification

- [x] 7.1 `uv run pytest` and `bun run test` green
- [ ] 7.2 Deploy, then confirm against live: new Claude rows carry a cost and a
      cache-write count, and the backfilled history stops reading as $0

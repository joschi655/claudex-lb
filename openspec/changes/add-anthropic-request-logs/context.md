# Context — Anthropic request logs

## Decisions

**`count_tokens` is excluded, not merely uninteresting.** Claude Code calls
`/v1/messages/count_tokens` routinely — before compaction, when sizing context, on tool
result assembly. Those calls consume no quota and return no completion. Logging them
would multiply the row count without adding served work, and every per-request average
in the dashboard (tokens, latency, cost) would sit next to the Codex numbers computed
over completions only. The exclusion keeps the two providers' statistics comparable.

**Cost stays NULL rather than being estimated from list prices.** There is no Claude
entry in the pricing table, so `calculated_cost_from_log` naturally returns None. That
is the right outcome, not a gap to fill: these are subscription seats, and the marginal
price of one more request against a Pro or Max plan is zero. Populating list-price
figures was considered as a "what this would have cost on the API" signal and rejected —
it would show spending that never happened, in the same column the Codex rows use for
money actually owed. If that comparison is wanted later it belongs in its own field with
its own name, not in `cost_usd`.

**Input counters are summed on the way in.** Anthropic reports `input_tokens` exclusive
of cached tokens plus separate cache-read and cache-write counters, whereas this
project's cost path computes billable input as `input_tokens - cached_input_tokens` —
that is, cached is a *subset*. Storing Anthropic's counters verbatim would make the same
column mean different things depending on which provider wrote the row, and would
understate prompt size by the entire cache hit. Cache writes are folded into the input
total at parity even though Anthropic bills them at a premium, because the schema has no
cache-write rate; the effect is confined to a cost path that is NULL for these models
anyway.

**Every attempt that got a response is its own row.** The alternative — one row per
client request, describing only the account that ultimately served it — would hide
exactly the events the pool exists to manage. A 429 that triggers failover is the
signal that an account is saturated; collapsing it into the successor's row makes a
degrading account invisible until it fails outright. A 401 that is repaired by a forced
refresh is likewise logged, so a credential that needs refreshing on every request is
visible as a pattern rather than as silent latency.

Attempts that never reached upstream — an account dropped by a failed refresh before any
request was sent — write nothing, because no attempt against the upstream occurred and a
row would imply otherwise.

**The useragent helper moved rather than being copied.** `_request_log_useragent_fields`
had nine importers inside the OpenAI proxy. The implementation now lives in
`app/core/usage/useragent.py`, with the old private name re-exported from
`app/modules/proxy/_service/support.py`. Copying it into the relay would have let the two
providers' `useragent_group` values drift apart, which is precisely the column reports
group by; rewriting all nine call sites would have added churn unrelated to this change.

## Streaming without buffering

The SSE path is the only interesting mechanism here. The relay already streamed chunks
straight through; usage now comes off those same bytes as they pass, via a line
accumulator that holds at most one partial line. Nothing is withheld from the client and
nothing accumulates with stream length. The parse is filtered before it is attempted:
only lines mentioning `message_start` or `message_delta` are handed to `json.loads`, so
the thousands of `content_block_delta` events in a long response cost a substring scan
each rather than a full parse.

The row is written in the generator's `finally`, which means a client disconnect
mid-stream still logs what was served up to that point — with the tokens counted so far
and no error, because a disconnect is not an upstream failure.

## Failure modes to watch

- **Log rows lost at shutdown.** Writes run on tracked background tasks that are not
  drained during shutdown — the same contract the existing usage-header writes have. A
  process killed mid-write loses that row. Accepted: the row is telemetry, and adding a
  drain would mean giving this lazily-constructed service a lifespan hook, which is a
  separate concern from emitting the rows at all.
- **`request_id` collisions across attempts.** Each row takes the upstream's `request-id`
  header when present and a fresh UUID otherwise, so two attempts never share an id.
- **Model recorded as empty string.** `request_logs.model` is NOT NULL. A request whose
  body is unparseable or omits `model` and which then fails before any response names one
  will log an empty model rather than being dropped. Losing the row entirely would be
  worse: the attempt still happened and still consumed the account.

# Claude Traffic in Statistics

Requests relayed to Claude accounts are recorded in the same request log as Codex
traffic, so they appear in the dashboard's request list, the reports pages, and
per-account token and latency figures without any extra configuration.

## What is recorded

Each upstream attempt against a selected account produces one row: the account, the
model, token counts, total latency, the client user agent, and — for streaming responses
— the time to first byte. Usage is read from the response as it streams, so nothing is
buffered and no chunk is held back from the client.

Anthropic reports prompt tokens as three separate counters (uncached input, cache reads,
cache writes). They are summed into `input_tokens`, with the cache-read portion also
recorded as `cached_input_tokens`. This matches how the Codex rows are stored, where
cached tokens are a subset of the input total, so the two providers' numbers can be read
side by side.

## Failover is visible

When an account is rate limited and the request fails over, both attempts are logged:
one error row naming the account that returned `429`, and one success row for the account
that served the request. An account that is starting to saturate therefore shows up in
the request list before it stops working entirely.

Refresh-driven retries appear the same way. If a request gets a `401`, has its token
refreshed, and then succeeds on the same account, you will see an error row followed by a
success row — a credential that needs refreshing on every request is visible as a
pattern.

## What is deliberately absent

**Token counting calls are not logged.** `POST /v1/messages/count_tokens` consumes no
quota and returns no completion, and Claude Code issues it frequently. Logging it would
fill the request list with empty rows and pull every per-request average away from the
Codex baseline.

**Cost is empty for Claude models.** A subscription seat has no marginal per-request
price, so the cost column stays blank rather than showing a list-price estimate of money
that was never spent. Token counts and latency are recorded in full.

---

*Spec: [anthropic-provider](https://github.com/Soju06/codex-lb/tree/main/openspec/specs/anthropic-provider)*

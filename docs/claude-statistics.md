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

## Reading one provider at a time

Every request row carries the provider of the account that served it, copied at write
time rather than looked up through the account, so the split survives an account being
deleted. Claude rows are marked with a badge in the request list; Codex rows are left
unmarked.

Once both providers have served traffic, a **Providers** filter appears on the request
list and a **Provider** filter on the reports page. Selecting one narrows every figure on
the page — totals, the model donut, cost per day, tokens per day, and the latency
percentiles. A deployment that only serves Codex never sees the control at all.

Two aggregates in particular are worth reading per provider rather than combined. Cost
per day mixes priced Codex rows with Claude rows that carry no price, so the combined
line understates nothing but describes two different things at once. The latency
percentiles average two upstreams with different response characteristics, so a combined
p95 can describe no request that actually happened.

## Clients other than Claude Code

Anthropic routes subscription traffic on the client identity the OAuth token was issued
against, so a request that does not look like Claude Code earns intermittent `5xx`
rather than a clean rejection. The relay therefore normalizes the upstream leg of every
OAuth-credentialed request: it sends the `claude-cli` user agent and `x-app: cli`, merges
the `claude-code-20250219` beta flag, and prefixes the request body's `system` field with
the Claude Code identity block. A caller that already presents as Claude Code is left
alone, and accounts holding a console API key are relayed verbatim — a static key is not
a Claude Code credential and disguising it would buy nothing.

The request log deliberately disagrees with the wire. It records the user agent the
*client* sent, not the one the proxy substituted, so any other client keeps its own slice
of the UserAgent breakdown on the reports page and can be filtered out of the Claude Code
figures. What that slice is named depends on the client: one that sets its own user agent
is grouped under it, while one that leaves the Anthropic SDK's default in place is grouped
under `Anthropic` along with every other SDK caller.

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

*Specs: [anthropic-provider](https://github.com/joschi655/claudex-lb/tree/main/openspec/specs/anthropic-provider),
[proxy-runtime-observability](https://github.com/joschi655/claudex-lb/tree/main/openspec/specs/proxy-runtime-observability)*

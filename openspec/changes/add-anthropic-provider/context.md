# add-anthropic-provider - context

## Purpose

Run OpenAI Codex and commercial Anthropic API traffic through one self-hosted
codex-lb instance while preserving strict credential, routing, quota, and
analytics boundaries.

## Decisions

- Anthropic Console API keys are the only Claude credential supported in v1.
  Claude.ai consumer OAuth login, token import, refresh, and subscription
  pooling are explicitly unsupported.
- Existing Anthropic OAuth rows are migrated to an inert legacy credential
  kind and deactivated. Operators can replace a specific row with a Console API
  key or delete it; migration never silently destroys secrets or history.
- A Console key has no discoverable email identity. Creation requires a display
  label, always creates a distinct row, and replacement targets an exact local
  account id. No key-based or label-based automatic merge occurs.
- The upstream request remains a transparent Messages API relay. The proxy may
  parse policy and usage fields, but forwards the original request bytes.
- API-key assignments and single-account routing are hard ownership boundaries.
  A Claude request never falls back to an OpenAI account or an unassigned
  Anthropic account.
- Provider is persisted on request logs so analytics remain correct after an
  account is deleted. Existing rows backfill to `openai`.
- Combined statistics include requests, tokens, errors, and latency. OpenAI
  subscription credits and Anthropic API rate limits are displayed separately.
  Unknown Anthropic cost remains null and makes the aggregate cost explicitly
  partial rather than appearing as zero.

## Failure modes

- A 401 invalidates an Anthropic API key and requires explicit replacement.
- A 429 records standard Anthropic rate-limit reset metadata and selects a
  different eligible key when available.
- Connection, TLS, header-wait, or pre-first-byte stream failures may fail over.
  Once response bytes are committed, the request is never replayed.
- Client disconnects settle owned reservations and close upstream resources but
  do not mark an otherwise healthy account unhealthy.
- Ordinary permission 403 responses pass through without invalidating the key.
- OpenAI-only services fail closed on an Anthropic account instead of relying
  on each caller to remember a filter.

## Example

An operator adds a key labelled `Production Claude` in Accounts, creates or
updates a codex-lb client API key assigned to that account, then configures:

```sh
ANTHROPIC_BASE_URL=https://codex-lb.example ANTHROPIC_AUTH_TOKEN=<codex-lb-key> claude
```

Claude Code sends the standard Messages request to codex-lb. The proxy validates
the client key and its account/model limits, selects only assigned Anthropic
API-key accounts, replaces client authentication with `x-api-key`, streams the
response, settles usage, and records an `anthropic` request log.

# add-anthropic-provider — context

## Purpose

Let one self-hosted codex-lb instance load-balance both OpenAI Codex accounts
(unchanged) and Anthropic Claude accounts. Claude Code clients point
`ANTHROPIC_BASE_URL` at the proxy and hold only a proxy API key; the proxy owns
and refreshes every Claude OAuth token centrally through the same cross-replica
single-writer refresh machinery Codex accounts already use.

## Why this shape

Claude Code already speaks the Anthropic Messages API, so the Claude path is a
transparent relay (auth injection + byte-for-byte SSE pass-through), not a
schema translation layer like the OpenAI compatibility surface. That keeps the
new code small and isolated:

- New, self-contained modules: `app/core/anthropic/` (oauth refresh, upstream
  dispatch/header builder, usage-header parser) and `app/modules/anthropic_proxy/`
  (routes + failover service).
- Surgical branches in shared files only: `Account` model (+`provider`,
  nullable `id_token_encrypted`, `access_token_expires_at`), `AuthManager`
  (provider branch in refresh/freshness), `LoadBalancer` (provider-scoped
  selection + cache key), account import (credential sniffing), `app/main.py`
  (router registration), and one-line provider filters on the per-account
  OpenAI schedulers.

The OpenAI hot paths are untouched: every new parameter defaults to the OpenAI
behavior, so existing call sites are byte-identical. This keeps future upstream
merges from `Soju06/codex-lb` feasible.

## Key decisions

- **Token custody fixes the re-login problem.** Claude OAuth refresh tokens are
  single-use and rotate on every refresh. Keeping credential copies on client
  machines eventually strands a stale refresh token. Centralizing refresh in the
  proxy's claim-serialized `AuthManager` removes that failure mode.
- **Static console credentials** (no refresh token) are first-class but never
  refreshed; they route last by default (`preserve` policy) and degrade to
  `reauth_required` on a 401 rather than attempting a refresh.
- **Freshness is expiry-based for anthropic** (refresh within 5 min of
  `access_token_expires_at`), not the OpenAI 8-day `last_refresh` age gate.
- **Endpoint:** bare `POST /v1/messages` + `/v1/messages/count_tokens` (plus an
  `/anthropic/v1` alias). `/v1/messages` was unclaimed by the OpenAI proxy.
- **Usage** is ingested passively from `anthropic-ratelimit-unified-*` response
  headers into the existing primary(5h)/secondary(7d) usage windows — on
  successes and on 429s (which report utilization at the cap) — so
  capacity-weighted selection reflects real Claude utilization with zero
  balancer changes. Active `/api/oauth/usage` polling is deferred (the endpoint
  is heavily rate-limited; passive headers dominate under traffic).
- **Re-import is the reauth repair path**, so the anthropic slot identity is
  (provider, email): importing a credential for a known email updates that row
  in place (tokens, expiry, reactivation) instead of duplicating it — a
  duplicate's sibling would strand a dead single-use refresh token. Accounts
  never merge across providers, even on a shared email.
- **Stream timeouts are idle-based** (`sock_read`), matching the rest of the
  proxy: an actively streaming SSE response is never cut by a total-duration
  cap; connection setup gets a short bounded budget.

## Failover semantics (relay)

Per request, bounded to 3 distinct accounts, never replaying after the first
streamed byte reached the client:

- 2xx → success (stream verbatim or return body); record success + ingest usage.
- 401 → one forced token refresh + one retry on the same account; a second 401
  marks `account_auth_invalidated` (→ `reauth_required`) and moves on. Static
  credentials skip the refresh and degrade immediately.
- 429 → mark rate-limited with the upstream reset time; try the next account.
- 403 with a revocation-shaped body → permanent failure; try the next account.
- Other 4xx → returned verbatim, no health write, no failover (client's fault).
- 5xx / connect error before first byte → record error; try the next account.
- Client disconnect mid-stream → close upstream, no health write.

## Example onboarding

```
curl -X POST http://<host>:2455/api/accounts/import \
  -F 'auth_json=@~/.claude-keychain-<email>.json'
```

Then on the client:

```
ANTHROPIC_BASE_URL=http://<host>:2455 ANTHROPIC_AUTH_TOKEN=<proxy-key> \
  claude -p "say hi"
```

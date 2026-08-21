## 1. Schema + provider-aware core

- [x] 1.1 Migration: `accounts.provider` (NOT NULL default `openai`), `id_token_encrypted` nullable, `access_token_expires_at` nullable int
- [x] 1.2 `app/core/providers.py` constants; `Account` model fields
- [x] 1.3 `app/core/anthropic/oauth.py`: Claude token refresh (RefreshError codes preserved)
- [x] 1.4 `AuthManager`: provider branch in `_refresh_tokens` / `_perform_refresh` / `ensure_fresh`; static-credential accounts never refresh
- [x] 1.5 Provider filters: usage refresh, reset credits, model refresh, quota planner; guardian expiry-based staleness for anthropic
- [x] 1.6 `LoadBalancer.select_account(provider=...)` + cache key; OpenAI call sites unchanged

## 2. Claude credential import

- [x] 2.1 `claudeAiOauth` payload sniffing in `import_account` → anthropic import path (ms→s expiry, `claude_` plan prefix)
- [x] 2.2 Static-credential import (no refresh token) → `preserve` routing policy
- [x] 2.3 Dashboard: `provider` in account schemas + badge; hide OpenAI-only actions for anthropic accounts

## 3. Anthropic Messages relay

- [x] 3.1 `app/core/anthropic/upstream.py`: header builder (auth injection, beta merge, static x-api-key) + dispatch
- [x] 3.2 `app/modules/anthropic_proxy/`: routes `POST /v1/messages`, `/v1/messages/count_tokens` (+ `/anthropic/v1` alias), proxy API key auth (`Authorization`/`x-api-key`), Anthropic error envelope
- [x] 3.3 Failover loop: 429/401/403/5xx matrix, one forced refresh per account per request, no mid-stream retry, disconnect ≠ unhealthy
- [x] 3.4 Register routers + SPA `excluded_prefixes` in `app/main.py`

## 4. Usage ingestion

- [x] 4.1 `anthropic-ratelimit-unified-*` header parser (permissive)
- [x] 4.2 Relay hook → `UsageHistory` primary/secondary rows + `reset_at`, throttled, selection-cache invalidation
- [x] 4.3 Usage polling — superseded by the completed
      `poll-anthropic-usage-api` change, which polls every OAuth account on the
      configured cadence and applies per-account cooldowns when Anthropic throttles

## 4b. Hardening (post-implementation audit)

- [x] 4b.1 Import dedupe: anthropic slot identity = (provider, email); re-import updates in place and reactivates `reauth_required` accounts
- [x] 4b.2 Provider guards: email-fallback merge never crosses providers; merge field copy carries `provider` + `access_token_expires_at`; anthropic slot lock key
- [x] 4b.3 Upstream stream timeout is idle-based (`sock_read`), bounded connect budget
- [x] 4b.4 Usage headers ingested from 429 responses (saturation signal)
- [x] 4b.5 Relay honors the operator-configured routing strategy
- [x] 4b.6 `expiresAt` unit tolerance (ms or s) on import; `retry-after` hint on the no-account 429
- [x] 4b.7 Guardian refresh pass carries plain account ids across the repo-session boundary (live drill caught `DetachedInstanceError`: closing the read-only session rolls back and expires its instances; latent upstream bug armed by enabling the guardian)

## 5. Validation

- [x] 5.1 Unit: refresh branch, freshness gates, static account, import parsing, header builder, failover matrix, usage parser
- [x] 5.2 Integration: import → relay stream via ASGITransport (429 failover, byte-identical relay, statuses persisted, usage ingested); OpenAI regression untouched
- [x] 5.3 Migration round-trip on sqlite; `uv run pytest`; `ruff`; strict OpenSpec validation
- [x] 5.4 Live drill (2026-07-19, ubuntu-tunnel): 6 accounts imported, real `/v1/messages` 200 + SSE stream, forced-expiry refresh with rotated-token persistence, rate-limited failover to second account, OpenAI row untouched, switcher timer disabled, guardian enabled (surfaced 4b.7)

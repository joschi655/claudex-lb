## Why

Operators who hold both OpenAI Codex accounts and Anthropic Claude accounts currently need two systems: codex-lb for Codex and ad-hoc credential switching (keychain/file swapping) for Claude. Claude OAuth refresh tokens are single-use and rotate on every refresh, so any scheme that keeps credential copies on client machines eventually strands a stale refresh token and forces a re-login. Centralizing Claude token custody in the proxy — with the same cross-replica single-writer refresh machinery Codex accounts already get — removes the failure mode structurally: clients hold only a proxy API key, never OAuth tokens.

## What Changes

- `accounts.provider` discriminator column (`openai` default, `anthropic` new); `id_token_encrypted` becomes nullable and `access_token_expires_at` (epoch seconds) is added for expiry-based freshness.
- Anthropic OAuth token refresh (`api.anthropic.com/v1/oauth/token`, Claude Code public client id) wired into the existing `AuthManager` single-writer refresh path; expiry-based freshness gate replaces the 8-day age gate for anthropic accounts.
- Static-credential anthropic accounts (imported without a refresh token, e.g. console API keys) are routable but never refreshed; auth failure moves them straight to `reauth_required`.
- Account import accepts the Claude Code credential shape (`claudeAiOauth` JSON) alongside the existing Codex `auth.json`.
- New transparent relay for the Anthropic Messages API: `POST /v1/messages` and `POST /v1/messages/count_tokens` (plus an `/anthropic/v1` alias), authenticated with existing proxy API keys, selecting an anthropic account per request with rate-limit/auth failover.
- Account selection, selection caching, and per-account schedulers become provider-scoped; OpenAI-only schedulers and account actions skip or reject anthropic accounts.
- Usage ingestion for anthropic accounts from `anthropic-ratelimit-unified-*` response headers (passive) plus sparse polling, feeding the existing primary/secondary usage windows.

No new `CODEX_LB_*` settings: the anthropic path activates only when an anthropic account exists.

## Capabilities

### New Capabilities

- `anthropic-provider`: multi-provider account custody and the Anthropic Messages relay.

### Modified Capabilities

- `account-routing`: selection MUST be provider-scoped; a request routed for one provider never lands on another provider's account.
- `usage-refresh-policy`: OpenAI usage refresh flows MUST skip anthropic accounts; anthropic usage comes from relay response headers plus sparse polling.

## Impact

`app/db/models.py` + one Alembic revision, `app/modules/accounts/auth_manager.py`, `app/modules/proxy/load_balancer.py`, `app/modules/accounts/service.py`, `app/main.py`, per-account schedulers (usage refresh, reset credits, model refresh, quota planner, auth guardian); new `app/core/anthropic/` and `app/modules/anthropic_proxy/` modules; dashboard account list gains a provider badge. Existing OpenAI behavior unchanged (defaults preserve current call-site semantics).

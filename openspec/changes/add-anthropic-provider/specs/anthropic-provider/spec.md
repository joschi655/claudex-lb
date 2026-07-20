# anthropic-provider Delta

## ADDED Requirements

### Requirement: Accounts carry a provider discriminator

Every account MUST have a `provider` value (`openai` or `anthropic`); existing accounts default to `openai`. Anthropic accounts MUST be persistable without an id token, and OAuth-backed anthropic accounts MUST persist the access-token expiry (epoch seconds).

#### Scenario: Existing accounts are unaffected

- **GIVEN** a database created before this change
- **WHEN** the migration runs
- **THEN** all existing accounts have `provider = "openai"` and their token material is unchanged

#### Scenario: Accounts never merge across providers

- **GIVEN** an OpenAI account and an anthropic credential sharing the same email
- **WHEN** the anthropic credential is imported (merge-by-email enabled or not)
- **THEN** two distinct accounts exist and the OpenAI account's provider and token material are unchanged

### Requirement: Anthropic token refresh uses the shared single-writer path

Anthropic OAuth refresh MUST go through the same claim-serialized, CAS-persisted refresh path as OpenAI accounts, calling the Anthropic token endpoint with the Claude Code public client id. A rotated refresh token MUST be persisted before the refresh outcome is visible to request handling. The freshness gate for anthropic accounts MUST be expiry-based (refresh when within 5 minutes of `access_token_expires_at`), not the OpenAI 8-day age gate.

#### Scenario: Concurrent refreshes serialize

- **GIVEN** two concurrent requests holding the same expired anthropic account
- **WHEN** both trigger a refresh
- **THEN** exactly one upstream refresh call happens and both requests observe the rotated token

#### Scenario: Dead refresh token surfaces as reauth

- **WHEN** the Anthropic token endpoint answers `invalid_grant`
- **THEN** the account status becomes `reauth_required` and the account leaves the selection pool

### Requirement: Static-credential anthropic accounts are never refreshed

An anthropic account imported without a refresh token (static credential, e.g. a console API key) MUST be routable, MUST never trigger a token refresh, and MUST move to `reauth_required` on an upstream auth failure without any refresh attempt.

#### Scenario: Static account auth failure

- **GIVEN** a static-credential anthropic account
- **WHEN** the upstream answers 401 for a relayed request
- **THEN** no refresh call is made and the account status becomes `reauth_required`

### Requirement: Claude credential import

Account import MUST accept the Claude Code credential shape — a JSON object containing `claudeAiOauth` with `accessToken`, `refreshToken` (optional for static credentials), `expiresAt` (milliseconds; an epoch-seconds value MUST be tolerated), and optional `scopes`/`subscriptionType` — and create an anthropic account with encrypted tokens, `plan_type` prefixed `claude_`, and expiry converted to epoch seconds. Static-credential imports MUST default to the `preserve` routing policy. Importing a credential whose email matches an existing anthropic account MUST update that account in place (tokens, expiry, plan, reactivation) instead of creating a duplicate; synthesized fallback emails carry no identity and never dedupe.

#### Scenario: Switcher backup file imports

- **WHEN** a `{"claudeAiOauth": {...}}` payload is imported with an email label
- **THEN** an active anthropic account exists with encrypted access/refresh tokens and `access_token_expires_at` in seconds

#### Scenario: Re-import repairs the existing account

- **GIVEN** an anthropic account in `reauth_required`
- **WHEN** a fresh credential for the same email is imported
- **THEN** the same account row holds the new tokens, is active again, and no duplicate account exists

### Requirement: Anthropic Messages relay

The proxy MUST expose `POST /v1/messages` and `POST /v1/messages/count_tokens` (and the same paths under `/anthropic/v1`), authenticated by existing proxy API keys via `Authorization` or `x-api-key`. The relay MUST pass request and response bodies through unmodified (including SSE streams byte-for-byte), replacing client auth headers with the selected account's credential: OAuth accounts get `Authorization: Bearer` plus the `oauth-2025-04-20` beta flag merged into `anthropic-beta`; static API-key credentials get `x-api-key` without the OAuth beta flag. Errors produced by the relay itself MUST use the Anthropic error envelope.

#### Scenario: Streaming pass-through

- **GIVEN** an anthropic account and a streaming Messages request
- **WHEN** the upstream responds with SSE
- **THEN** the client receives the upstream bytes unmodified and `anthropic-*` response headers are forwarded

#### Scenario: Client auth never reaches upstream

- **WHEN** a request carrying a proxy API key is relayed
- **THEN** the upstream request contains the account credential and no proxy API key material

### Requirement: Relay failover and health

The relay MUST select accounts with the operator-configured routing strategy, and the upstream stream timeout MUST be idle-based (an actively streaming response is never cut off by a total-duration cap). On upstream failures the relay MUST fail over to a different anthropic account (bounded attempts), never re-sending a request after its first streamed byte reached the client. Outcome handling MUST be: 429 → mark the account rate-limited with the upstream reset time and try the next account; 401 → force one token refresh and retry the same account once, a second 401 marks the account `reauth_required`; revocation-shaped 403 → permanent failure; other 4xx → returned to the client verbatim with no account-health write; 5xx/connect errors before the first byte → record an error and try the next account. A client disconnect mid-stream MUST NOT mark the account unhealthy. When no anthropic account is selectable the relay MUST answer with an Anthropic-shaped 429 including a retry hint.

#### Scenario: Rate-limited account fails over

- **GIVEN** two active anthropic accounts
- **WHEN** the first answers 429 with a reset header
- **THEN** the first account is marked rate-limited with that reset time and the request succeeds on the second account

#### Scenario: 401 refreshes once then degrades

- **WHEN** an upstream 401 arrives for an OAuth anthropic account
- **THEN** the relay forces exactly one refresh and retries that account once; a second 401 sets `reauth_required` and the relay moves on

#### Scenario: No mid-stream account switch

- **GIVEN** a streaming response that fails after bytes reached the client
- **THEN** the relay aborts without retrying on any account

### Requirement: Anthropic usage ingestion

The relay MUST parse `anthropic-ratelimit-unified-*` response headers opportunistically (missing or malformed headers are ignored, never an error) — on success responses and on 429s, which report utilization at the cap — and persist 5h/7d utilization into the existing primary/secondary usage windows so selection weights reflect real utilization. Active polling of the Anthropic usage endpoint MUST be sparse: only for accounts without a recent passive snapshot.

#### Scenario: Headers drive selection weights

- **WHEN** a relayed response reports 5h utilization for the account
- **THEN** a subsequent selection observes that utilization without any additional upstream call

#### Scenario: 429 saturation is recorded

- **WHEN** an upstream 429 carries unified rate-limit headers
- **THEN** the account's utilization snapshot is persisted alongside the rate-limit health write

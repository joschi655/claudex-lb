# anthropic-provider Specification

## Purpose

Define provider-safe Anthropic Console API-key custody, canonical Messages API
relay behavior, and provider-aware analytics without supporting Claude.ai
consumer OAuth credentials or subscription pooling.

## Requirements

### Requirement: Accounts carry typed provider and credential kind

Every account MUST identify its upstream provider and credential kind.
Supported production combinations are `openai/openai_oauth` and
`anthropic/anthropic_api_key`. Existing Anthropic rows created from consumer
OAuth credentials MUST migrate to an unsupported legacy kind, MUST be
deactivated, and MUST never enter account selection.

#### Scenario: Existing OpenAI rows remain active

- **GIVEN** a database created before provider support
- **WHEN** all provider migrations run
- **THEN** existing accounts are typed as OpenAI OAuth without changing tokens or status

#### Scenario: Legacy Anthropic OAuth is quarantined

- **GIVEN** an Anthropic row created by the experimental OAuth implementation
- **WHEN** the credential-kind migration runs
- **THEN** the row is deactivated and cannot be selected until explicitly replaced

### Requirement: Anthropic API-key onboarding

The dashboard MUST allow a write-authorized operator to create a labelled
Anthropic Console API-key account and replace the key on an exact Anthropic
account id. Keys MUST be encrypted at rest, MUST never be returned or logged,
and MUST NOT be merged by label or synthetic email. Replacing a legacy row MUST
convert it to `anthropic_api_key` and reactivate it. Claude.ai OAuth payloads
MUST be rejected.

#### Scenario: Create a Console key account

- **WHEN** an operator submits a non-empty label and API key
- **THEN** a distinct active Anthropic API-key account is created and the response contains no secret

#### Scenario: Replace a legacy credential

- **GIVEN** a deactivated legacy Anthropic account
- **WHEN** an operator replaces its credential with a Console API key
- **THEN** the same account id becomes an active Anthropic API-key account

### Requirement: Anthropic Messages relay

The proxy MUST expose canonical `POST /v1/messages` and
`POST /v1/messages/count_tokens` routes authenticated by existing codex-lb API
keys. The relay MUST forward the original request body and replace client
authentication with the selected account's `x-api-key`. Proxy-produced errors
MUST use the Anthropic error envelope. The routes MUST use the same firewall,
bulkhead, and bounded request-body protections as other `/v1` proxy routes.

#### Scenario: Streaming pass-through

- **GIVEN** an eligible Anthropic API-key account and a streaming request
- **WHEN** upstream returns SSE
- **THEN** the client receives the upstream bytes in order and no client credential reaches upstream

#### Scenario: Oversized chunked body

- **WHEN** a chunked request exceeds the configured relay limit
- **THEN** reading stops at the limit and the proxy returns an Anthropic-shaped size error without dispatching upstream

### Requirement: API-key policy and accounting are preserved

The relay MUST enforce client API-key account assignments, exact single-account
routing, model allowlists/enforcement, request limits, usage reservations, and
settlement. It MUST update the client key's last-used timestamp and write one
provider-tagged request log for every relayed outcome. Reservation cleanup MUST
run after partial errors and client cancellation. Count-token requests MUST
reserve zero output tokens. Because Anthropic request cost is intentionally
unpriced, the relay MUST reject a request before reservation and upstream
dispatch when its client API key has a global or exact-model `cost_usd` limit;
cost limits filtered to other models MUST NOT block the request.

#### Scenario: Assigned accounts are a hard boundary

- **GIVEN** a client key assigned to one Anthropic account
- **WHEN** that account is unavailable
- **THEN** the request fails without selecting any unassigned account

#### Scenario: Usage settles after a stream

- **WHEN** a streaming response completes with Anthropic usage events
- **THEN** the reservation and request log contain the observed token totals

#### Scenario: Count tokens reserves no output quota

- **GIVEN** a count-tokens payload containing `max_tokens`
- **WHEN** the client API-key usage reservation is created
- **THEN** its output-token budget is zero

#### Scenario: Unpriced cost limit fails closed

- **GIVEN** a client API key with a `cost_usd` limit applicable to the requested Claude model
- **WHEN** the client sends a Claude request
- **THEN** the relay returns an Anthropic-shaped policy error without reserving usage or dispatching upstream

### Requirement: Relay failover and health are bounded

The relay MUST try only distinct eligible Anthropic accounts and MUST never
replay after response bytes are committed. Connection, TLS, response-header,
and pre-first-byte failures MAY fail over. A `401` MUST invalidate an API-key
credential; `429` MUST record the best available reset and try the next eligible
account; ordinary `403` and other client `4xx` responses MUST pass through
without health degradation; `5xx` before first byte MAY fail over. Client
disconnects MUST close upstream resources and MUST NOT mark the account
unhealthy.

#### Scenario: Empty successful stream fails over

- **GIVEN** upstream returns 2xx headers but disconnects before the first SSE byte
- **WHEN** another eligible account exists
- **THEN** the first attempt is recorded as an error and the second account is tried before committing a response

#### Scenario: No mid-stream replay

- **GIVEN** response bytes have reached the client
- **WHEN** the stream fails or the client disconnects
- **THEN** no other account receives the request

### Requirement: Provider-aware analytics and presentation

Accounts, dashboard overview, projections, and request-log APIs MUST accept an
`all`, `openai`, or `anthropic` provider scope, defaulting to `all`. Request logs
MUST persist provider independently of account lifetime. Combined scope MUST
aggregate traffic metrics, while OpenAI credits/depletion and Anthropic API
rate limits remain separately labelled and MUST NOT be summed into one capacity
number. A cost aggregate containing unpriced requests MUST identify itself as
partial.

#### Scenario: Combined traffic with separate capacity

- **GIVEN** OpenAI and Anthropic request logs
- **WHEN** the dashboard loads with provider scope `all`
- **THEN** request/token/error metrics include both providers and capacity remains provider-specific

#### Scenario: Claude account controls are provider-specific

- **WHEN** an operator selects an Anthropic account
- **THEN** the dashboard offers key replacement and generic lifecycle/routing actions without OpenAI OAuth, reset-credit, probe, export, or warmup controls

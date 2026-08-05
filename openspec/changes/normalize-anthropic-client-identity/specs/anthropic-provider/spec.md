# anthropic-provider Delta

## ADDED Requirements

### Requirement: Upstream Claude Code identity for OAuth credentials

When the selected account's credential is an OAuth token, the relay MUST present the
upstream request as Claude Code. The upstream request MUST carry a
`claude-cli/<version> (external, cli)` user-agent, `x-app: cli`, and the
`claude-code-20250219` beta flag merged into `anthropic-beta` alongside
`oauth-2025-04-20`. The request body's `system` field MUST begin with the Claude Code
identity text block; a `system` supplied as a plain string MUST be converted to the
block-list shape to accommodate it, and a body with no `system` field MUST gain one.

Normalization MUST be idempotent and MUST NOT rewrite a caller that already presents
as Claude Code: a client user-agent whose product token is `claude-cli` MUST be
forwarded with its own version intact, and a `system` field whose first block already
carries the identity text MUST leave the body unmodified.

Credentials that are static console API keys MUST NOT receive any of this
normalization — neither the headers nor the body transform — and MUST continue to be
relayed verbatim.

#### Scenario: Non-Claude-Code caller is normalized upstream

- **GIVEN** an OAuth-credentialed anthropic account
- **WHEN** a client relays a Messages request with user-agent `hermes-agent/1.0` and a
  `system` string of its own
- **THEN** the upstream request carries `claude-cli/<version> (external, cli)`,
  `x-app: cli`, an `anthropic-beta` containing both `oauth-2025-04-20` and
  `claude-code-20250219`, and a `system` block list whose first block is the Claude
  Code identity text followed by the client's original text

#### Scenario: Claude Code passes through unchanged

- **GIVEN** an OAuth-credentialed anthropic account
- **WHEN** a client relays a request whose user-agent is `claude-cli/2.1.0 (external, cli)`
  and whose `system` already begins with the Claude Code identity block
- **THEN** the upstream request carries that same user-agent version and the request
  body is forwarded byte-for-byte

#### Scenario: Static API keys are not disguised

- **GIVEN** an anthropic account holding an `sk-ant-api…` console key
- **WHEN** any client relays a Messages request
- **THEN** the upstream request body is unmodified and no Claude Code user-agent,
  `x-app`, or `claude-code-20250219` beta is injected

#### Scenario: Missing system field

- **GIVEN** an OAuth-credentialed anthropic account
- **WHEN** a client relays a Messages request with no `system` field
- **THEN** the upstream body carries a `system` block list containing exactly the
  Claude Code identity block

### Requirement: Request logs record the calling client, not the upstream identity

The `useragent` and `useragent_group` recorded on a relayed request MUST come from the
client's request headers, independent of any upstream identity normalization. A caller
that is rewritten to Claude Code on the upstream leg MUST still aggregate under its own
user-agent group in reports.

#### Scenario: Normalized caller stays distinguishable in reports

- **GIVEN** a client sending user-agent `hermes-agent/1.0` through an OAuth account
- **WHEN** the request is relayed and logged
- **THEN** the request-log row records `useragent_group = "hermes-agent"` even though
  the upstream request presented as `claude-cli`

## MODIFIED Requirements

### Requirement: Anthropic Messages relay

The proxy MUST expose `POST /v1/messages` and `POST /v1/messages/count_tokens` (and the same paths under `/anthropic/v1`), authenticated by existing proxy API keys via `Authorization` or `x-api-key`. The relay MUST pass response bodies through unmodified (including SSE streams byte-for-byte). The request body MUST be passed through unmodified except for the Claude Code identity normalization applied to OAuth-credentialed requests. Client auth headers MUST be replaced with the selected account's credential: OAuth accounts get `Authorization: Bearer` plus the `oauth-2025-04-20` beta flag merged into `anthropic-beta`; static API-key credentials get `x-api-key` without the OAuth beta flag. Errors produced by the relay itself MUST use the Anthropic error envelope.

#### Scenario: Streaming pass-through

- **GIVEN** an anthropic account and a streaming Messages request
- **WHEN** the upstream responds with SSE
- **THEN** the client receives the upstream bytes unmodified and `anthropic-*` response headers are forwarded

#### Scenario: Client auth never reaches upstream

- **WHEN** a request carrying a proxy API key is relayed
- **THEN** the upstream request contains the account credential and no proxy API key material

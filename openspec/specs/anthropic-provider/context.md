# Context: anthropic-provider

Normative requirements live in [`spec.md`](./spec.md). This document records
the rationale, constraints, failure modes, and operational setup for the
Anthropic provider.

## Purpose and scope

codex-lb runs OpenAI Codex and commercial Anthropic Messages API traffic
through one self-hosted proxy while preserving separate credentials, routing,
quota presentation, and provider-filtered analytics. The Anthropic path is
enabled only after an operator stores an Anthropic Console API key.

Claude.ai consumer login, token import, refresh-token custody, and Free, Pro,
or Max subscription pooling are non-goals. Console API keys avoid the rotating
consumer-token custody problem, but operators remain responsible for their own
Anthropic terms, billing, organization policy, and key-sharing controls.

## Decisions

- An account carries an explicit provider and credential kind. An Anthropic
  request cannot select an OpenAI account even when a client key is assigned to
  accounts from both providers.
- Console keys have no email identity. Creation requires an operator label and
  always creates a distinct row; replacement targets one exact account id.
- The proxy relays canonical Messages API request bytes and swaps only the
  client authentication for the selected upstream `x-api-key`.
- Combined analytics cover compatible traffic measures. OpenAI subscription
  credits and Anthropic rate-limit snapshots remain separate, and unknown
  Anthropic pricing produces a partial cost total rather than zero.

## Constraints and failure modes

- A `401` invalidates the selected Console key and requires explicit
  replacement. Ordinary permission `403` responses do not invalidate it.
- A `429` stores standard request/token reset metadata and may try another
  assigned eligible Anthropic account.
- Connection, TLS, header-wait, and pre-first-byte failures may fail over. Once
  response bytes reach the client, replay is forbidden.
- Client disconnects settle owned reservations and close upstream resources
  without marking an otherwise healthy account unhealthy.
- Existing experimental Anthropic OAuth rows are quarantined rather than
  silently deleted, preserving history while preventing selection.

## Operational example

An operator adds a Console key labelled `Claude Production`, creates a
codex-lb client API key assigned to that account, then runs:

```bash
ANTHROPIC_BASE_URL=https://codex-lb.example \
ANTHROPIC_AUTH_TOKEN=sk-clb-example \
claude
```

Claude Code sends standard `/v1/messages` traffic. codex-lb validates the
client key, enforces account and model scope, selects only eligible Anthropic
API-key accounts, forwards with the upstream Console key, settles usage, and
records an `anthropic` request log.

Published setup instructions live in
[`docs/claude-setup.md`](../../../docs/claude-setup.md). Related provider
boundaries are governed by the `account-routing`, `api-keys`,
`api-firewall`, and `usage-refresh-policy` capabilities.

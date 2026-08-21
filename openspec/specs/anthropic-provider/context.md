# Anthropic Provider Context

## Purpose and scope

claudex-lb extends codex-lb with a native Anthropic Messages path. Claude Code
already speaks that protocol, so the fork relays it directly instead of translating
it to an OpenAI schema:

```text
Claude Code → claudex-lb /v1/messages → pooled Anthropic accounts
Codex clients → claudex-lb Responses API → pooled ChatGPT accounts
```

The capability covers credential custody, refresh, provider-scoped selection,
failover, quota ingestion, and the externally visible relay contract. The normative
behavior is in [spec.md](spec.md).

## Why the proxy owns Claude credentials

Claude OAuth refresh tokens rotate and are single-use. If several clients retain
copies, the first refresh strands the others with stale material. claudex-lb keeps
the account credentials centrally, serializes refresh across replicas, and gives
clients only a claudex-lb proxy key. Static Anthropic Console keys are supported as
a separate credential kind and are never refreshed.

This is intentionally a fork capability. Upstream codex-lb remains focused on
ChatGPT/Codex accounts, which keeps its provider surface and maintenance scope
smaller.

## Security constraints

- A client proxy key must never be forwarded to Anthropic.
- Account credentials are encrypted at rest and are injected only on the upstream
  request leg.
- Selection is provider-scoped, including cache keys, so an OpenAI request cannot
  receive an Anthropic credential and vice versa.
- A rotated refresh token is persisted before request handling can observe success.
- Remote deployments should expose the proxy only through TLS and require proxy API
  keys.

## Failure modes

- A 429 records quota state and may fail over to another Anthropic account.
- One 401 can force a serialized refresh; repeated authentication failure removes
  the account from routing until it is re-imported.
- A client error is returned without poisoning account health.
- A request is never replayed after response bytes reach the client.
- Client disconnects and idle-poll throttling do not mark otherwise healthy accounts
  unhealthy.

## Concrete setup

Import a Claude Code credential backup through the authenticated dashboard or account
import API. Then point Claude Code at the proxy and provide a claudex-lb API key:

```bash
ANTHROPIC_BASE_URL=http://127.0.0.1:2455 \
ANTHROPIC_AUTH_TOKEN=sk-clb-your-proxy-key \
claude -p "Reply with OK only."
```

For a remote instance, use an `https://` base URL. The relay exposes both
`/v1/messages` and `/v1/messages/count_tokens`; Claude Code appends those paths to
`ANTHROPIC_BASE_URL` itself.

## Related contracts

- [Account routing](../account-routing/spec.md)
- [Usage refresh policy](../usage-refresh-policy/spec.md)
- [Proxy runtime observability](../proxy-runtime-observability/spec.md)

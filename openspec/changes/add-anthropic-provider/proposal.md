## Why

Operators using both OpenAI Codex and the Anthropic Messages API should not need
separate proxy and observability systems. The first implementation used
Claude.ai consumer OAuth credentials, but Anthropic's authentication policy
does not permit third parties to offer Claude.ai login or route Free, Pro, or
Max credentials. Production support therefore needs to use commercial
Anthropic API keys and enforce provider separation at every shared boundary.

## What Changes

- Add a typed account provider and credential kind. Existing Anthropic OAuth
  rows are quarantined and cannot be selected until explicitly replaced with
  an Anthropic Console API key.
- Add dashboard APIs and forms to create or replace encrypted Anthropic API-key
  accounts. Claude.ai OAuth payloads are rejected.
- Keep the standard Anthropic Messages endpoints at `/v1/messages` and
  `/v1/messages/count_tokens`, using existing proxy API keys and commercial
  Anthropic API keys upstream.
- Enforce API-key account assignments, model policy, usage reservations,
  settlement, request logging, firewall rules, bounded bodies, and safe
  pre-response failover on the Anthropic relay.
- Make every OpenAI-only account consumer reject or skip Anthropic credentials.
- Add provider-scoped accounts, request logs, overview statistics, and shared
  `All | OpenAI | Claude` dashboard views. Traffic may aggregate across
  providers; incompatible quota/capacity units do not.

No new `CODEX_LB_*` setting is introduced. The Anthropic path is available only
when an operator explicitly stores an Anthropic API key.

## Capabilities

### New Capabilities

- `anthropic-provider`: provider-safe Anthropic API-key custody and Messages
  relay.

### Modified Capabilities

- `account-routing`: account selection and all provider-specific dispatchers
  are provider-scoped.
- `usage-refresh-policy`: OpenAI refresh and quota flows never receive
  Anthropic credentials; Anthropic rate-limit metadata is passive only.

## Impact

Account and request-log schema, account onboarding APIs, Anthropic relay,
OpenAI per-account schedulers/actions, dashboard queries, account management,
and published client setup documentation. Existing OpenAI behavior and routes
remain the default for call sites without an explicit provider.

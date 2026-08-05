## Why

The Anthropic relay forwards the client's own fingerprint upstream: user-agent,
`x-app`, and the request body's system prompt all arrive at `api.anthropic.com`
exactly as the caller sent them. That was correct while the only caller was Claude
Code, whose fingerprint is the one Anthropic's OAuth endpoints expect. It stops
being correct the moment a second client points at the proxy.

The pool's credentials are Claude Code OAuth tokens. Anthropic routes OAuth traffic
on the client fingerprint, and OAuth requests that do not carry it are documented by
other Claude-Code-compatible clients as drawing intermittent 5xx. Today every
non-Claude-Code caller spends the pool's OAuth accounts while presenting as
something else — so a fingerprint mismatch shows up as account errors and failover
churn attributed to the account, not to the caller that caused it.

The proxy is the only place that knows which credential kind is about to be used, so
it is the only place that can normalize the fingerprint without every client
reimplementing it. Doing it here also keeps the client honest in the other
direction: the request log records who actually called, so a mixed pool stays
readable even though the upstream leg is uniform.

## What Changes

- OAuth-credentialed upstream requests carry the Claude Code fingerprint: a
  `claude-cli/<version> (external, cli)` user-agent, `x-app: cli`, and the
  `claude-code-20250219` beta merged alongside the existing `oauth-2025-04-20`.
- The request body's `system` field gains the Claude Code identity block as its
  first element when the caller did not already supply it. Both the string and
  block-list shapes of `system` are handled, and a body that already leads with the
  block is forwarded byte-for-byte.
- Callers that already present as Claude Code are passed through untouched — their
  own user-agent version is preserved rather than overwritten with the proxy's.
- Static console API keys (`sk-ant-api…`) keep today's verbatim pass-through. The
  Claude Code identity belongs to OAuth traffic and would be wrong on a console key.
- Request logs keep recording the *client's* user-agent, not the normalized upstream
  one, so the existing UserAgent report filter and distribution donut continue to
  separate callers.

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `anthropic-provider`: the relay's request-body pass-through becomes a normalized
  pass-through for OAuth credentials, and upstream header construction gains the
  Claude Code identity.

## Impact

- Code: `app/core/anthropic/upstream.py` (headers), a new
  `app/core/anthropic/client_identity.py` (body transform),
  `app/modules/anthropic_proxy/service.py` (apply per credential kind).
- Schema: none.
- Frontend: none. The UserAgent filter and donut already bucket by
  `useragent_group`, and this change is specifically written to keep feeding them
  the client's identity.
- Tests: identity-transform unit coverage for both `system` shapes and the
  idempotence case, plus relay coverage proving the upstream leg is normalized while
  the logged user-agent is not.

## Simplicity

No new `CODEX_LB_*` settings. The behavior is zero-config and unconditional for
OAuth credentials, because a fingerprint that is only sometimes correct is worse
than one that is always correct — an operator toggle here would exist solely to
select a known-worse upstream contract. No new README section, `.env.example` entry,
or dashboard nav item. The body transform runs only when the caller has not already
supplied the identity block, so the byte-for-byte path that Claude Code takes today
is unchanged.

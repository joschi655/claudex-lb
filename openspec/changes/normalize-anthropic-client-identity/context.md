# Context

## What "presenting as Claude Code" actually consists of

Four things, in descending order of how much upstream appears to care:

1. **The leading system block.** OAuth-scoped Anthropic traffic is expected to open its
   `system` with the exact text `You are Claude Code, Anthropic's official CLI for
   Claude.` as its own text block. This is the part that is inspected, and the part a
   client cannot fake by fiddling with headers.
2. **`anthropic-beta: claude-code-20250219`**, merged with the `oauth-2025-04-20` flag
   the relay already injects.
3. **`user-agent: claude-cli/<version> (external, cli)`**.
4. **`x-app: cli`**.

Other Claude-Code-compatible clients that reimplement this note that omitting the
fingerprint on OAuth traffic produces *intermittent* 5xx rather than a clean 4xx — the
failure mode is flaky, not diagnostic, which is what makes it worth fixing centrally
instead of per-caller.

## Why the proxy and not the client

The credential kind is not knowable to the caller. A client holding an `sk-clb-…` proxy
key cannot tell whether the request will be served by an OAuth subscription account or a
static console key, and the correct fingerprint differs between the two: a console key
with a `claude-cli` user-agent and a Claude Code system prefix is a lie with no upside.
The relay picks the account, so the relay is the only component positioned to decide.

This also removes a class of client-side hack. Clients that gate their Claude Code
costume on the *key prefix* (a common pattern — `sk-ant-` means OAuth, `sk-ant-api`
means console) get the wrong answer for `sk-clb-…` keys and would need either a patched
prefix table or a hand-minted key to behave. Neither survives a key rotation.

## Why the request log deliberately disagrees with the wire

The upstream leg is uniform on purpose; the log is not. `request_log_useragent_fields`
reads the client headers at the top of `relay()`, before any account is selected and
before `build_upstream_headers` runs, so the row records who called and the wire records
what the pool needs. That asymmetry is the whole point: reports already expose a
UserAgent filter and a distribution donut keyed on `useragent_group`, with a pass-through
bucketing expression that gives any new product token its own slice. A second client
therefore becomes visible in statistics the first time it sends a request, with no
schema, API, or UI change — but only for as long as the log keeps reading the client
headers. Hence the explicit requirement; it exists to stop a future refactor from
"simplifying" the log to use the headers actually sent upstream.

## Concrete example

A caller sends:

```http
POST /v1/messages
user-agent: hermes-agent/1.0
x-api-key: sk-clb-…

{"model":"claude-sonnet-4-5","system":"You are Hermes, a helpful autonomous agent.","messages":[…]}
```

With an OAuth account selected, upstream receives:

```http
POST https://api.anthropic.com/v1/messages
user-agent: claude-cli/2.1.0 (external, cli)
x-app: cli
anthropic-beta: oauth-2025-04-20, claude-code-20250219
Authorization: Bearer sk-ant-oat…

{"model":"claude-sonnet-4-5","system":[
  {"type":"text","text":"You are Claude Code, Anthropic's official CLI for Claude."},
  {"type":"text","text":"You are Hermes, a helpful autonomous agent."}
],"messages":[…]}
```

and the request-log row records `useragent = "hermes-agent/1.0"`,
`useragent_group = "hermes-agent"`.

## Deliberate non-goals

- **No product-name scrubbing.** Clients that mention themselves by name inside their
  prompts keep doing so; the relay prepends an identity block and does not rewrite the
  caller's text. Search-and-replace over arbitrary prompt content is a correctness
  hazard (it would corrupt a prompt that legitimately discusses those names) and buys
  nothing the leading block does not already buy.
- **No per-client configuration.** The transform depends on the credential kind, not on
  which client is calling. Nothing in the proxy needs to know that Hermes exists.
- **`count_tokens` is normalized too but never logged.** It shares the body shape and
  the same upstream expectations; it is simply excluded from `request_logs` today, which
  this change does not alter.

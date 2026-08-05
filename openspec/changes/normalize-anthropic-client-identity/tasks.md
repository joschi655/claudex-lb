# Tasks

## 1. Upstream identity module

- [x] 1.1 Add `app/core/anthropic/client_identity.py` with the Claude Code identity
      constants (system text, `claude-code-20250219` beta, pinned `claude-cli` version)
      and `apply_claude_code_identity(body: bytes) -> bytes`.
- [x] 1.2 Handle every `system` shape: absent, string, block list. Convert a string to
      a block list when prepending. Leave the body bytes untouched when the first block
      already carries the identity text, and when the body is not decodable JSON object.
- [x] 1.3 Extend `build_upstream_headers` to take the credential kind into account:
      inject `user-agent`/`x-app` and merge the `claude-code-20250219` beta only for
      OAuth credentials, preserving a client user-agent whose product token is
      `claude-cli`.

## 2. Relay wiring

- [x] 2.1 In `AnthropicProxyService.relay`, compute the normalized body once per relay
      call (lazily, memoized) and send it only on attempts using an OAuth credential;
      static-key attempts keep sending the original bytes.
- [x] 2.2 Confirm `request_log_useragent_fields` continues to read the *client* headers
      before any normalization, and add a comment binding that ordering to the spec so a
      later refactor cannot silently merge Hermes traffic into the Claude Code bucket.

## 3. Tests

- [x] 3.1 Unit: identity transform over all `system` shapes, idempotence, non-JSON and
      non-object bodies, and that the original bytes are returned (not re-serialized)
      when no change is needed.
- [x] 3.2 Unit: header construction for OAuth vs static credentials, and the
      `claude-cli` client passthrough case.
- [x] 3.3 Relay: a `hermes-agent` request against an OAuth account reaches upstream with
      the Claude Code fingerprint while the written request-log row keeps
      `useragent_group = "hermes-agent"`.
- [x] 3.4 Relay: a static-key account relays the body byte-for-byte.

## 4. Validation

- [x] 4.1 `uv run pytest` for the touched modules.
- [x] 4.2 `uv run ruff check` / format.
- [x] 4.3 `openspec validate normalize-anthropic-client-identity --strict`.

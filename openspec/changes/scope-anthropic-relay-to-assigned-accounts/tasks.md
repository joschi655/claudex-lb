# Tasks

## 1. Plumb the scope to the relay

- [x] 1.1 In `app/modules/anthropic_proxy/api.py`, derive the scoped account ids from
      the authenticating key and pass them to `relay`. Pass nothing when scoping is
      disabled, when the assignment set is empty, or when there is no key.
- [x] 1.2 Accept the ids in `AnthropicProxyService.relay` and forward them to
      `select_account` as `account_ids`.

## 2. Tests

- [x] 2.1 Relay: a scoped key restricts selection to its assigned ids.
- [x] 2.2 Relay: failover happens within the scope and never leaves it.
- [x] 2.3 Relay: an unscoped key, an empty assignment set, and no key at all each
      leave selection unrestricted.
- [x] 2.4 API: the route reads the scope off the authenticated key.

## 3. Validation

- [x] 3.1 `uv run pytest` for the touched modules.
- [x] 3.2 `uv run ruff check` / format.
- [x] 3.3 `openspec validate scope-anthropic-relay-to-assigned-accounts --strict`.

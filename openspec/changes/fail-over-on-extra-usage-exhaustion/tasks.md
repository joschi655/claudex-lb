# Tasks

## 1. Classification

- [x] 1.1 Add an exhaustion marker and a `_looks_like_usage_exhaustion(body)` helper
      to `app/modules/anthropic_proxy/service.py`, matching the shape of the existing
      `_looks_like_revocation`.

## 2. Relay wiring

- [x] 2.1 Handle the exhaustion `400` above the generic `4xx` branch: record the
      attempt as `rate_limit_exceeded`, `mark_rate_limit` the account, keep the body
      as `last_error`, and break to the next account.
- [x] 2.2 Leave the generic `4xx` branch otherwise unchanged.

## 3. Tests

- [x] 3.1 Relay: a drained first account is skipped and the second account's success
      reaches the caller.
- [x] 3.2 Relay: when every account is drained, the caller gets the upstream `400`
      body unchanged.
- [x] 3.3 Relay: an ordinary `400` still returns verbatim without a second attempt.
- [x] 3.4 Request log: the drained attempt is recorded as `rate_limit_exceeded`.

## 4. Validation

- [x] 4.1 `uv run pytest` for the touched modules.
- [x] 4.2 `uv run ruff check` / format.
- [x] 4.3 `openspec validate fail-over-on-extra-usage-exhaustion --strict`.

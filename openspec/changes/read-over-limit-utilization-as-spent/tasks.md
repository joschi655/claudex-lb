# Tasks

## 1. Parser

- [x] 1.1 Read the unified utilization headers as a fraction unconditionally and clamp
      the result to 100, removing the already-a-percentage tolerance.

## 2. Tests

- [x] 2.1 An over-limit fraction (`1.0`, `1.04`, `1.5`, `2`) records as 100% used, on
      both the five-hour and weekly headers.
- [x] 2.2 Existing fraction, case-insensitivity, missing-header and malformed-value
      behaviour is unchanged.
- [x] 2.3 Confirm 2.1 fails against the pre-fix parser.

## 3. Validation

- [x] 3.1 `uv run pytest` for the touched modules and the wider Anthropic surface.
- [x] 3.2 `uv run ruff check` / format.
- [x] 3.3 `openspec validate read-over-limit-utilization-as-spent --strict`.
- [x] 3.4 Deploy, then confirm the affected account's stored window matches
      `/api/oauth/usage` instead of reading ~1%. `claude-a@example.com` five-hour
      window read `1.04` before and `100.0` after, against `/api/oauth/usage`'s
      authoritative `100.0`.

# Tasks

## 1. Usage-API client

- [x] 1.1 Add `app/core/anthropic/usage_api.py`: `fetch_anthropic_usage(access_token, *,
      route=None)` issuing `GET /api/oauth/usage` with the bearer token and the
      `oauth-2025-04-20` beta flag, through the shared outbound client.
- [x] 1.2 Parse the payload into a snapshot: `five_hour`/`seven_day` utilization plus
      `resets_at` (ISO 8601 → epoch), and a budget bucket discovered by scanning
      top-level objects for a non-null `limit_dollars`.
- [x] 1.3 Parse the extra-usage credit figures (`spend.used`/`spend.limit` minor units
      with exponent, and `extra_usage.is_enabled`).
- [x] 1.4 Raise a typed error distinguishing throttled (429), unauthorized (401), and
      other failures; never raise for a shape the parser does not recognize.

## 2. Persistence

- [x] 2.1 Extend `persist_usage_snapshot` (or add a sibling) to write a `budget` window
      row with the bucket utilization, reset, and the dollar figures in the existing
      `credits_*` columns.
- [x] 2.2 Confirm a polled window replaces the stored sample rather than merging with it.

## 3. Scheduler wiring

- [x] 3.1 Poll each Anthropic OAuth account from the loop that already ticks for Anthropic
      (`UsageRefreshScheduler._refresh_anthropic_windows`), before warmup evaluation, so
      warmup reasons about freshly polled window state.
- [x] 3.2 Skip static API-key credentials.
- [x] 3.3 Per-account cooldown on 429; per-account failures swallowed so one account
      cannot stop the others or the warmup pass.
- [x] 3.4 Skip a write that only restates the stored row, until a minimum interval
      elapses; never defer a changed snapshot.

## 4. Presentation

- [x] 4.1 Add the spend block to `AccountSummary` and populate it in the accounts mapper
      from the `budget` usage row.
- [x] 4.2 Render the spend bar in the accounts view for accounts that report a budget.
- [x] 4.4 Render it in the compact account list row too. 4.2 was completed against the
      account *detail* panel only, and every branch in the list row keys off a rolling
      window, so a budget seat rendered with no quota information at all -- the one
      outcome the requirement names explicitly. Task 6.4, which would have caught it
      against the live check24 seat, was never run.
- [x] 4.3 Surface the budget in the menu-bar payload so a usage-based seat shows a number
      instead of nothing.

## 5. Tests

- [x] 5.1 Unit: parser over the real subscription payload, the real budget payload, a
      payload whose budget sits under an unknown key, an all-null payload, and malformed
      input.
- [x] 5.2 Unit: 429 → throttled error, 401 → unauthorized error.
- [x] 5.3 Persistence: a budget payload writes a `budget` row with dollars; a
      subscription payload writes primary/secondary and no budget row.
- [x] 5.4a Poller: an unchanged snapshot is not rewritten each tick, a changed one is
      written immediately, and an unchanged one is refreshed once the interval lapses.
- [x] 5.4 Scheduler: an idle account's stale row is replaced by the polled value; a 429
      account is skipped while its cooldown holds; a raising poll still leaves the other
      accounts polled and warmup running.
- [x] 5.5 API: an account with a budget row exposes the spend block; a window account does
      not.

## 6. Validation

- [x] 6.1 `uv run pytest` for the touched modules.
- [x] 6.2 `uv run ruff check` / format.
- [x] 6.3 `openspec validate poll-anthropic-usage-api --strict`.
- [ ] 6.4 Deploy and confirm against live accounts: the stale row corrects itself and the
      usage-based seat shows its budget.

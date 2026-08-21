# Tasks

## 1. Closed-window key

- [x] 1.1 Derive the closed-window attempt key from the observation time bucketed to
      the cooldown, replacing the constant that could never come round again.
- [x] 1.2 Thread the key through the candidate helpers so both windows use the same
      period.

## 2. Per-window cooldown

- [x] 2.1 Add `latest_by_account_window` to the warmup repository, partitioned by
      `(account_id, window)`.
- [x] 2.2 Select the candidate before consulting the cooldown, and read the cooldown for
      the candidate's window.

## 3. Live data

- [x] 3.1 Close out the stuck `pending` attempt on `claude-b@example.com` so the
      audit trail carries no permanent in-flight row. Attempt 2 (window `primary`,
      key `0`, opened 2026-08-05 13:18) marked `failed` / `warmup_never_completed`;
      no stranded rows remain.

## 4. Tests

- [x] 4.1 Unit: a closed window is warmed again in a later period; twice inside one
      period sends one ping.
- [x] 4.2 Unit: a stale `pending` attempt does not lock the account out — the live
      failure, reproduced.
- [x] 4.3 Unit: a weekly ping does not delay the next five-hour ping.
- [x] 4.4 Unit: a failed ping is not retried against the other window.
- [x] 4.5 Integration: `latest_by_account_window` reports per window, takes the newest
      per window, and omits accounts with no attempts.
- [x] 4.6 Confirm 4.1–4.3 fail against the pre-fix code.

## 5. Validation

- [x] 5.1 `uv run pytest` for the touched modules.
- [x] 5.2 `uv run ruff check` / format.
- [x] 5.3 `openspec validate retry-closed-window-warmups --strict`.
- [x] 5.4 Deploy. Confirmed on the running container: the closed-window key is now a
      moving value and advances with the cooldown period, both windows still select
      their own candidate, and the previously-blocking row is inert.
- [x] 5.5 Confirm an actual scheduled warm-up lands once a window next closes.
      `claude-a@example.com`'s five-hour window elapsed at 12:49:59; a scheduled
      warm-up fired 30s later keyed on that reset, succeeded, and its response headers
      opened a fresh window (0% used, reset 17:50). Request logged with
      `source=limit_warmup`, `request_kind=warmup`.

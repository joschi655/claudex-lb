## Why

A Claude subscription seat has two rolling windows, and both start on the account's first
request rather than on a calendar: five hours, and seven days. Warmup was built for the
short one and only ever looks at it.

The weekly window has the same failure mode, on a longer and more expensive timescale. An
account whose week has just reset does not begin a new one until something spends a
request. Stay idle for two days and the next weekly reset lands on day nine instead of
day seven — the quota did not grow, it just arrived later, and every subsequent cycle
inherits the drift. That is exactly the loss the five-hour ping exists to prevent.

The gap is invisible today because the trigger reads only the five-hour row. An account
mid-way through a live five-hour window is never even considered, which is the common
case: the short window is running almost whenever anything is happening, so the one
moment the weekly window needs a ping is the moment warmup has already skipped the
account.

The same misconception sits in the on-demand trigger. It refuses any account whose stored
five-hour row carries no reset timestamp — but that is not "no window", it is a window
that has *run out*, which the scheduled pass has treated as warmable since the usage poll
landed. The manual trigger therefore switches itself off in precisely the state an
operator reaches for it.

## What Changes

- The Anthropic warmup pass evaluates the weekly window alongside the five-hour one. A
  weekly window that has run out — an elapsed reset, or the usage API's `utilization: 0`
  with a null `resets_at` — makes the account a warmup candidate even while its five-hour
  window is still running.
- A candidate is chosen five-hour-first. One ping opens every closed window at once, so
  when both have run out the five-hour attempt already covers the weekly one and no
  second request is sent.
- A weekly attempt is recorded under its own window name, so it dedupes against weekly
  state instead of colliding with the five-hour trigger's records.
- The on-demand trigger's eligibility gate reads whether a rolling window is *on record*,
  not whether it is currently running, and accepts a weekly row as well as a five-hour
  one. A seat that reports no window at all — a usage-based seat — is still refused.

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `anthropic-provider`: the warmup trigger covers both rolling windows rather than the
  five-hour one alone, and the on-demand trigger's eligibility gate is stated in terms of
  a window being on record.

## Impact

- Code: `app/modules/limit_warmup/service.py` (candidate selection across both windows),
  `app/core/usage/refresh_scheduler.py` (reads the weekly window and passes it),
  `app/modules/accounts/service.py` (trigger eligibility gate).
- Migration: none. `account_limit_warmups` already keys attempts by window name, and
  `secondary` is the name the Anthropic usage ingest has always written.
- Tests: `tests/unit/test_anthropic_limit_warmup.py`,
  `tests/integration/test_anthropic_limit_warmup_api.py`.
- Specs: this change's deltas, on top of `add-anthropic-limit-warmup` and
  `poll-anthropic-usage-api`.

## Simplicity

No new settings and no new endpoint. The weekly window is read from a table the scheduler
already opens a session on, evaluated by the function that already decides five-hour
candidacy, and governed by the same global switch, per-account toggle, and cooldown. An
install that never enables warmup sees no change; an install that enables it gets the
behaviour it already believed it had.

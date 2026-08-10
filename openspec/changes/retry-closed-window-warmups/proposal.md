## Why

Warm-up silently stopped working for a live account, and would eventually have
stopped for every account.

An attempt is deduped on the reset timestamp of the window it acts on. For a
running window that is a real identity: stable while the window lasts, different
for the next one. A **closed** window has no reset timestamp, so a constant stood
in for one — and a constant never comes round again. The attempt table's guard
therefore stopped being "one ping per closed-window episode" and became "one ping
per account per window, for the life of the row".

Observed on `ge37wuc@matlab.rbg.tum.de`: an attempt created 2026-08-05 13:18 was
left `pending` by a restart mid-flight and still held the key three days later.
While the usage poll reported real reset timestamps the account was warmed every
five hours, nine times running. At 2026-08-08 10:00 the poll wrote the window's
true state — no reset — and every evaluation from then on collided with that
stale row. The account went **46 hours** with a dead five-hour window and no log
line to say why; it only recovered when real traffic happened to open it. Two of
the three Claude accounts had already banked their one-and-only attempt at the
constant key, so they were queued up to fail the same way.

Separately, the cooldown is charged per account while the two windows close on
unrelated schedules — a weekly reset at 07:00 says nothing about when the five
hours run out. A weekly ping therefore held the next five-hour ping back by up to
a full cooldown: an hour off a five-hour window, a fifth of it, for no reason.

## What Changes

- A closed window's attempt is keyed on the observation time bucketed to the
  cooldown, instead of a constant. Concurrent replicas evaluating the same closed
  window in the same period still collapse to one attempt; the next period is a
  new key, so the trigger re-arms as often as the cooldown would allow anyway.
- A stale attempt left `pending` by a restart can no longer lock an account out:
  its key belongs to a period that has passed.
- The warm-up cooldown is read for the window being acted on rather than for the
  account, so an independently-closing weekly window cannot delay the five-hour
  one.
- The candidate is selected **before** the cooldown is consulted. That ordering
  is what stops per-window cooldowns from doubling the ping rate: when both
  windows are closed the five-hour one wins on precedence every tick, so a failed
  attempt waits on its own cooldown instead of falling through to the weekly
  window.

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `anthropic-provider`: the closed-window trigger is stated as repeatable, and the
  warm-up cooldown is stated per window rather than per account.

## Impact

- Code: `app/modules/limit_warmup/service.py` (closed-window key, cooldown read
  per window, candidate selected first), `app/modules/limit_warmup/repository.py`
  (`latest_by_account_window`).
- Data: existing attempts keyed on the old constant become inert rather than
  blocking. The one stuck `pending` row on the live database is closed out as
  part of the deploy so the audit trail does not carry a permanent in-flight
  attempt.
- Migration: none. No schema change; the key is a value, not a column.
- Tests: `tests/unit/test_anthropic_limit_warmup.py`,
  `tests/integration/test_limit_warmup_repository.py`.
- Specs: this change's deltas, on top of `add-anthropic-limit-warmup`,
  `poll-anthropic-usage-api`, and `warm-the-weekly-claude-window`.

## Simplicity

No new settings, no new column, no new endpoint. The bucket period is the
cooldown that already governs warm-up, so the two cannot drift apart and there is
nothing extra to tune. The per-window cooldown reuses the attempt table's existing
`window` column through one added query.

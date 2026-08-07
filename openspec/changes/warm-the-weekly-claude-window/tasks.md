# Tasks

## 1. Candidate selection

- [x] 1.1 Generalize the elapsed-window test in `app/modules/limit_warmup/service.py` to
      take the window it is evaluating, so the same "elapsed reset, or no reset at all,
      but only when a row exists" rule serves both windows.
- [x] 1.2 Add a candidate picker that tries the five-hour window first and falls back to
      the weekly one, so two closed windows still cost one ping.
- [x] 1.3 Accept the weekly window state in `run_anthropic_window_refresh`, defaulted so a
      caller that passes only the five-hour state keeps its current behaviour.

## 2. Scheduler wiring

- [x] 2.1 Read the `secondary` window rows in `_refresh_anthropic_windows`, in the session
      already opened for the primary rows, and pass them through.

## 3. On-demand trigger

- [x] 3.1 Gate the trigger on a rolling window being on record rather than on a live reset
      timestamp, and accept a weekly row as well as a five-hour one.

## 4. Tests

- [x] 4.1 Unit: a closed weekly window is warmed while the five-hour window runs, and the
      attempt is filed under the weekly window name.
- [x] 4.2 Unit: an elapsed weekly reset is warmed; a running weekly window is left alone.
- [x] 4.3 Unit: two closed windows send one ping, attributed to the five-hour window.
- [x] 4.4 Unit: a seat with no weekly row is not warmed for one; a caller that omits
      weekly state keeps the five-hour trigger.
- [x] 4.5 Integration: the trigger warms an account whose five-hour window has run out,
      and one that reports only a weekly window; a seat with no window at all is still
      refused.

## 5. Validation

- [x] 5.1 `uv run pytest` for the touched modules.
- [x] 5.2 `uv run ruff check` / format.
- [x] 5.3 `openspec validate warm-the-weekly-claude-window --strict`.
- [ ] 5.4 Deploy and confirm against live accounts: an account whose weekly window has run
      out while its five-hour window runs gets a ping, and its weekly reset moves forward.

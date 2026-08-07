# Context

## The drift being prevented

A weekly window is 10080 minutes long and starts at the account's first request. That
makes idleness compound: a week that starts two days late ends two days late, and the
account has spent nine days to receive seven days of quota. Nothing recovers the
difference later — the next cycle simply starts from wherever the last one ended.

The five-hour ping has always been justified this way. The weekly window is the same
mechanism with 33× the cost of getting it wrong.

## Why the gap was invisible

The trigger read one row:

```python
candidate = _anthropic_elapsed_window_candidate(latest_primary.get(account.id), now=now_epoch)
```

An account whose five-hour window is running produces no candidate and is never looked at
again in that pass. But a running five-hour window is the *normal* state whenever anything
is happening on the pool, so the moment a freshly reset weekly window needs its ping is
reliably the moment the account is skipped. The failure never announced itself; it looked
like an account that simply had not been warmed yet.

## A worked example

Stored window rows for one Claude Pro seat, read live:

| window | used | resets in | window_minutes |
|---|---|---|---|
| `primary` | 36% | 180 min | 300 |
| `secondary` | 1% | 10020 min | 10080 |

The weekly window had been open 60 minutes. Had that account stayed idle instead, the
`secondary` row would have read `utilization: 0, resets_at: null` — closed — while
`primary` kept a live reset three hours out. Under the old rule that account was not a
candidate, and the weekly window would have stayed unstarted for as long as the idleness
lasted.

## Decisions

**Five-hour first, one ping.** A warmup is an ordinary Messages request; the upstream
starts *every* closed window it belongs to. So when both windows are closed the five-hour
attempt already opens the weekly one, and picking a second candidate would spend a request
to open a window that is already open. The weekly window is therefore only chosen when the
five-hour window is running — the one case the short trigger structurally cannot reach.

**The attempt is filed under its own window name.** `account_limit_warmups` dedupes on
`(account_id, window, reset_at)`. Filing a weekly attempt as `primary` would let a
five-hour attempt at the same reset timestamp suppress it, and would misreport which
window an operator's ping opened.

**Presence, not liveness, is what "has a window" means.** `reset_at IS NULL` on a stored
row is how the usage API reports a window that has *run out* — the exact state warmup
exists to leave. Only a missing row means "this seat has no such window", which is how a
usage-based seat reports. The scheduled pass has read it that way since the usage poll
landed; the on-demand trigger still read `reset_at is not None` and refused the account,
so the manual button was unavailable in the state that most warranted it.

## Failure modes considered

- **A warmup that cannot land.** If the ping fails (quota spent, upstream down), the
  weekly row keeps its reset value, the attempt row keeps that value as its dedupe key,
  and no retry is made for the same state. Identical to the five-hour behaviour: warmup is
  discretionary traffic and never retries into a wall.
- **A stale weekly row.** If the poll has not yet corrected a row whose reset has elapsed,
  one ping is sent and the response headers rewrite the window. The dedupe key prevents a
  second ping for the same stale value.
- **Banking the weekly window on purpose.** An operator who wants a weekly window to stay
  unstarted until a big session begins is now opted out of that by warmup — which is
  already true of the five-hour window, and is why warmup is per-account rather than
  fleet-wide.

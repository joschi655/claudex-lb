# Context — per-account pace gates

## Why "pace" rather than another threshold

The pool already has percentage caps: `DashboardSettings` carries sticky budget thresholds, and
accounts can be marked `preserve`. Both answer "how much", and neither answers "how fast". An
account 40% through its weekly quota is either comfortably behind schedule or badly ahead of it
depending only on the day, and a flat cap cannot see the difference. The even-pace line makes the
time axis explicit, which is what the operator intent — "leave the owner enough" — actually depends
on.

## Decisions

**Gates are hard filters, not preferences.** The alternative was to rank gated accounts last and
let them serve when nothing else could. That was rejected: a gate is a promise about someone else's
quota, and a preference that silently degrades under load breaks the promise exactly when traffic
is heaviest. This also matches the project's existing trapdoor rule that excluded accounts must
genuinely leave the selection loop.

**Unknown window bounds mean the gate does not apply.** Fail-closed was considered and rejected.
Anthropic window telemetry is harvested from response headers, so an account that has never served
traffic has no reset timestamp; fail-closed would make such an account permanently unselectable and
unable to ever acquire the data that would clear the gate. Fail-open is bounded: the account is
still subject to status, budget, and policy gates, and the window becomes known after its first
served request. Server-side warmup will narrow the gap further by opening windows deliberately.

**The gate reads routing-effective usage.** `AccountState.used_percent` already includes an
in-flight pressure term (a fraction of a point per concurrent request) used to spread load. The
gate reads that value rather than the raw stored percentage. The deviation is small and biases
toward excluding, which is the conservative direction here; introducing a parallel raw-usage field
purely for gate arithmetic would add a second source of truth for the same quantity.

**Weekly window length is a constant.** Upstream reports a reset timestamp for the secondary window
but not its length, and the pace line needs a length. Both providers bill the secondary window over
seven days, so `SECONDARY_WINDOW_MINUTES` is defined once and carried on `AccountState`, where a
future provider-specific value can override it per account without touching the arithmetic.

**Partial updates use a field-set sentinel, not value inspection.** `None` clears a gate, so
"omitted" and "explicitly null" must be distinguishable. The API reads Pydantic's
`model_fields_set` and the repository takes a `PaceGateUpdate` whose members are one-tuples when
supplied. Inferring intent from the value would have made clearing a gate impossible.

## Worked example

An account whose owner works evenings, shared into the pool during the day:

```json
{"preResetWindowMinutes": 120, "paceMarginPrimaryPct": 0, "paceMarginSecondaryPct": 20}
```

Read together: the account may serve only in the last two hours of its 5h window (so a fresh window
is left intact for its owner), only while its 5h usage is at or below the 5h pace line, and only
while its weekly usage is 20 points below the weekly line. Any one of the three failing removes it
from selection.

## Failure modes to watch

- **Every account gated at once.** Selection returns "All accounts are excluded by pace gates" and
  the request fails. This is intended — the gates were configured to protect quota — but an operator
  who gates the whole pool will see hard failures rather than degraded service. The error names the
  cause so it is diagnosable.
- **Gates plus a paused pool.** Gated accounts are excluded from the diagnostic message, so an
  operator sees the blocker they can actually clear ("All accounts are paused") rather than a
  message coloured by accounts that are merely pacing.
- **Clock skew against upstream reset timestamps.** The pace line is computed from the upstream
  reset timestamp and local time. Meaningful skew shifts the line; the elapsed fraction is clamped
  to `[0, 1]`, so skew degrades the line's accuracy without producing nonsensical values.

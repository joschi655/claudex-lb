## Why

A Claude subscription seat that has spent its allowance does not answer with `429`.
It answers with `400 invalid_request` and the body:

```
You're out of extra usage. Add more at claude.ai/settings/usage and keep going.
```

The relay reads every `4xx` as a caller mistake — validation, oversized payload,
unknown model — and returns it verbatim without touching account health and without
trying another account. That reading is right for the shapes it was written for and
wrong for this one: nothing about the request is malformed, and the same bytes would
succeed on any other account in the pool.

The failure is observable. On a four-account pool where one seat sat at 15% of its
five-hour window and the rest at 85%+, the drained seat returned this `400` twice in
twelve minutes. Both times the request ended there. The three healthy accounts were
never asked, and the caller saw a hard error from a pool that had capacity.

It also reads as a client bug. The row lands in the request log as
`invalid_request`, so a pool whose seats are cycling through exhaustion looks like a
client sending bad requests rather than a pool that needs another account.

## What Changes

- A `400` whose body names spent subscription usage is classified as account
  exhaustion, not as an invalid request: the account is marked rate-limited and the
  relay fails over to the next candidate, exactly as a `429` does today.
- The attempt is recorded as `rate_limit_exceeded` rather than `invalid_request`, so
  the request log attributes it to the account that ran dry.
- Every other `4xx` keeps today's verbatim pass-through. The classifier matches the
  exhaustion wording only; an unrecognized `400` is still the caller's problem.
- When no account can serve the request, the caller still receives the last upstream
  body unchanged — the exhaustion message reaches them once the pool is genuinely
  out, rather than on the first drained seat.

Marking it rate-limited rather than quota-exceeded is deliberate. The quota path
pins `used_percent` to 100 and holds the account for an hour; the observed recovery
was under three minutes, and the seat's real utilization was 15%. Rate-limit backoff
starts at a 30-second cooldown and lengthens only if the account keeps failing, which
matches what the seat actually does.

## Impact

- Affected specs: `anthropic-provider`
- Affected code: `app/modules/anthropic_proxy/service.py`
- No configuration, no schema change, no new setting. Behavior changes only for a
  `400` that previously ended the request.

# Context

## What the response actually looks like

Observed on a `claude_pro` seat roughly three hours into its five-hour window, with
about 15% of the window's allowance left:

```
HTTP/1.1 400 Bad Request
content-type: application/json

{"type":"error","error":{"type":"invalid_request_error",
 "message":"You're out of extra usage. Add more at claude.ai/settings/usage and keep going."}}
```

There are no `anthropic-ratelimit-*` headers on it. The status and the error type
both say the caller sent something wrong; only the message says otherwise. That is
why the classifier has to read the body.

## Why it looked like a client bug

Two of these arrived twelve minutes apart on a four-account pool. Between them the
same client, the same model, and the same conversation succeeded eleven times — on
the same account and on others. The rows landed in the request log as
`invalid_request`, which pointed the investigation at the caller's payload for far
longer than it should have. Nothing about the payload was ever wrong.

## Why rate-limited and not quota-exceeded

`handle_quota_exceeded` sets `used_percent = 100.0`, holds a fixed 120-second
cooldown, and writes `reset_at = now + 3600` when the error carries no reset hint —
which this one does not. Applying it here would claim a seat sitting at 15%
utilization is fully spent, and would surface that number on the dashboard and in the
menu-bar plugin.

`handle_rate_limit` leaves `used_percent` alone, starts at a 30-second floor, and
lengthens through `backoff_seconds(error_count)` if the account keeps failing. The
observed seat recovered in under three minutes and then served normally for the rest
of the window, so a short self-lengthening cooldown describes it better than a flat
hour.

## What this does not do

It does not top anything up, and it does not hide a genuinely empty pool: once every
candidate is drained the caller still receives the upstream `400` and its message,
which is the actionable one. What changes is that they receive it after the pool has
been asked, not after the first drained seat.

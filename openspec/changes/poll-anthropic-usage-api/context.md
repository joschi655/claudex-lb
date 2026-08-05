# Context

## The endpoint

`GET https://api.anthropic.com/api/oauth/usage`, with the account's OAuth bearer token and
`anthropic-beta: oauth-2025-04-20`. It answers for subscription credentials only. Two
shapes matter, and they are quite different.

A subscription seat:

```json
{
  "five_hour": {"utilization": 100.0, "resets_at": "2026-08-05T12:50:00.124511+00:00",
                "limit_dollars": null, "used_dollars": null, "remaining_dollars": null},
  "seven_day": {"utilization": 57.0,  "resets_at": "2026-08-06T10:00:00.124537+00:00",
                "limit_dollars": null, "used_dollars": null, "remaining_dollars": null},
  "seven_day_opus": null, "tangelo": null, "nimbus_quill": null, "cinder_cove": null,
  "extra_usage": {"is_enabled": false, "monthly_limit": null, "used_credits": null, …},
  "limits": [{"kind": "session", "percent": 100, "severity": "critical", …},
             {"kind": "weekly_all", "percent": 57, "severity": "normal", …}],
  "spend": {"used": {"amount_minor": 0, "currency": "USD", "exponent": 2},
            "limit": null, "percent": 0, "enabled": false, …}
}
```

A usage-based enterprise seat:

```json
{
  "five_hour": null,
  "seven_day": null,
  "cinder_cove": {"utilization": 77.72440259999999,
                  "resets_at": "2026-09-30T20:47:10.939005+00:00",
                  "limit_dollars": 1000, "used_dollars": 777.244026,
                  "remaining_dollars": 222.75597400000004},
  "extra_usage": {"is_enabled": true, "monthly_limit": 20000, "used_credits": 1603.0,
                  "utilization": 8.015, "currency": "USD", "decimal_places": 2, …},
  "limits": [],
  "spend": {"used": {"amount_minor": 1603, "currency": "USD", "exponent": 2},
            "limit": {"amount_minor": 20000, "currency": "USD", "exponent": 2},
            "percent": 8, "enabled": true, …}
}
```

Two things to note about the second shape. There are no windows at all, which is why such
a seat currently shows no quota information anywhere in the dashboard — nothing ever
writes a row for it. And the budget arrives under `cinder_cove`, one of a set of rotating
code words the payload reserves slots for (`tangelo`, `iguana_necktie`,
`omelette_promotional`, `nimbus_quill`, `cinder_cove`, `amber_ladder`, and the
`seven_day_*` family). Anthropic evidently renames these; matching on the key name would
break the moment the name rotates, so recognition is by the presence of `limit_dollars`.

`utilization` here is a **percentage** (`100.0`, `77.72`, `57.0`), which is worth stating
because the response *headers* the relay reads report the same quantity as a **fraction**
(`0.91` for 91%). `parse_unified_usage` carries a heuristic for that — values at or below
1 are read as fractions. The polled values need no heuristic.

## Why polling and not better header handling

The production incident that motivated this had two independent causes, and only the
second is fixable by looking at more data.

An account's stored five-hour history on 2026-08-05 ran 44%, 60%, 75%, 91%, and then a
single sample of 1.06% at 09:59:11 — after which the account served no further traffic and
that row stood as its state. The usage API, asked two hours later, reported the same
window (identical `resets_at`) at 100%. The account was spent; the pool believed it had
98% free and would have kept selecting it.

Header ingestion cannot defend against the first cause on its own. It holds one sample per
window with no history to judge a new one against, and rejecting a downward sample as
implausible would be wrong in the one case that matters most — a genuine window rollover
looks exactly like that. What is fixable is the second cause: nothing ever looked again.
A poll on a fixed cadence bounds how wrong the pool's picture can get to one refresh
interval, whatever the cause, and needs no heuristic about which samples to trust.

## Throttling is expected

The endpoint 429s readily, and observed doing so mid-diagnosis for one of four accounts
polled in the same second. Claude Code polls the same endpoint during a session against
the same account, so the pool is sharing a budget with the clients it serves. A 429 is
therefore traffic shaping and not an account fault: it must not touch account status, must
not log as an error, and must back that account's poll off. The stored sample simply stays
as it is until the next successful poll — which is the pre-existing behaviour, so a
throttled poll leaves the system no worse than before this change.

## Why `budget` is a usage window and not a new table

`usage_history.window` is an unconstrained string column, and the table already carries
`credits_has`, `credits_unlimited`, and `credits_balance` for the OpenAI credit case. A
dollar budget is the same shape as a window — a utilization, a reset instant, and a
remaining balance — so it fits without a migration. `capacity_for_plan` returns `None` for
every Claude plan (`normalize_account_plan_type("claude_enterprise")` is not in
`ACCOUNT_PLAN_TYPES`), so no synthetic credit arithmetic is applied to these rows and the
fleet summaries that weight by plan capacity continue to skip them.

The alternative considered was the `additional_usage_history` table with a registry entry.
It was rejected: that registry is keyed on quota names and carries a routing-policy
semantic, and the bucket names here rotate — the registry would need an entry per code
word, which is the coupling this change is specifically avoiding.

## Why

A Codex session on the operator's Mac died with `Invalid \`previous_response_id\`.`
and stayed dead. Every following turn produced the same error until the operator
abandoned the session.

The proxy caused it, and the proxy already contains the machinery to recover from
it. Neither half fired.

**The proxy pins the anchor itself.** On a Codex websocket session the service
injects a `previous_response_id` the client never sent, so it can trim the input
it forwards upstream (`websocket_session_anchor_injected`). On session
`01a01e5e-cde0-77f3-9e71-710bfdb54cd5` it pinned `resp_06a90a3c…873a0`, completed
at 11:04:14Z, and re-sent that same anchor at 11:16:10Z, 11:16:30Z, 11:19:07Z and
11:25:49Z — trimming 189, 190 and 191 client items down to 4, 5 and 6. Upstream
rejected all four:

```
status=error  error_code=invalid_request_error
error_message='Invalid `previous_response_id`.'
transport=websocket  model=gpt-5.6-sol
```

Because the anchor is re-derived from the session's request log on every turn, a
rejection is not a transient failure. It is a session that cannot make progress
again, over an anchor the client never chose and cannot clear.

**The recovery exists and is unreachable.** The websocket path already retains
the client's untrimmed body as a retry-safe replay whenever it injects an anchor,
and already knows how to drop the anchor, reconnect, and replay that body as a
fresh turn. That path is gated on `is_previous_response_not_found_error`, which
recognises exactly one upstream wording — a message containing both "previous
response" and "not found". The wording upstream actually used contains neither:

```
'Invalid `previous_response_id`.'                  -> not recognised
"Previous response with id 'resp_x' not found."    -> recognised
```

So the classifier decided this was an ordinary client-side invalid-request, and
the raw upstream 400 was forwarded verbatim to Codex — the one outcome the
existing requirements say a continuity miss must never produce.

## What Changes

- The upstream-anchor-rejection classifier stops matching one sentence and starts
  matching the condition. A message that names `previous_response_id` and calls it
  invalid means the same thing to this proxy as one that says the previous
  response was not found: the anchor is gone, so drop it and resend in full.
- The classifier stops requiring upstream to label the offending field. An
  `invalid_request_error` whose message itself names `previous_response_id` is
  classified on that message; an error naming a *different* `param` still is not.

Everything downstream of the classifier is unchanged. The full-resend replay, the
fail-closed rewrite to a retryable `stream_incomplete`, and the masking of the
missing response id from public payloads all already exist and already have
requirements; this change only lets the wording upstream sends reach them.

## Capabilities

### Modified Capabilities

- `responses-api-compat`: the continuity-miss requirements become statements about
  an upstream that rejected our anchor, rather than about one particular sentence
  upstream might use to say so.

## Impact

- Server: `app/core/errors.py` — `is_previous_response_not_found_message` and
  `is_previous_response_not_found_error`. No call site changes: the websocket
  recovery, the HTTP bridge rebind, and the public-error masking all already route
  through these two predicates.
- Tests: `tests/unit/test_previous_response_anchor_classifier.py`,
  `tests/integration/test_websocket_rejected_anchor_recovery.py`.
- Specs: `openspec/specs/responses-api-compat/spec.md`.
- No schema change, no migration, no new setting.
- Not included: the anchor *selection* itself. The same session shows a completed
  `resp_08f0604e…` at 11:18:01Z, yet 11:25:49Z still pinned the 11:04 anchor. That
  is a separate defect in which completed response becomes the anchor, and it is
  left open rather than folded in here. See `context.md`.

## Simplicity

No new `CODEX_LB_*` setting, no new recovery path, no new error code. The change
is a widening of two boolean predicates so that existing, already-specified
behaviour is reachable from a second upstream wording. Nothing defaults on that
was previously off, because nothing new exists to default.

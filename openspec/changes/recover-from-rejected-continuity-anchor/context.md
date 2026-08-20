# Context

## The live incident

ubuntu-tunnel, container `codex-lb`, 2026-08-20. Codex session
`01a01e5e-cde0-77f3-9e71-710bfdb54cd5`, model `gpt-5.6-sol`, all four turns on the
same account.

```
11:04:14Z  resp_06a90a3c…873a0                       status=success
11:16:10Z  websocket_session_anchor_injected  response_id=resp_06a90a3c…873a0  original_items=189 trimmed_to=4
11:16:11Z  ws_97e9d525…  error  invalid_request_error  'Invalid `previous_response_id`.'
11:16:30Z  websocket_session_anchor_injected  response_id=resp_06a90a3c…873a0  original_items=190 trimmed_to=5
11:16:30Z  ws_985c032d…  error  invalid_request_error  'Invalid `previous_response_id`.'
11:19:07Z  ws_93c81779…  error  invalid_request_error  'Invalid `previous_response_id`.'
11:25:49Z  websocket_session_anchor_injected  response_id=resp_06a90a3c…873a0  original_items=191 trimmed_to=6
11:25:49Z  ws_d8ad31db…  error  invalid_request_error  'Invalid `previous_response_id`.'
```

The client's item count climbs (189 → 190 → 191) because Codex keeps appending
the user's next turn to a conversation it believes is intact. The proxy keeps
discarding almost all of it in favour of an anchor upstream will not accept.

## Why the wording differs at all

Upstream has at least two ways of refusing an anchor. `previous_response_not_found`
with a message naming the missing id is the one this codebase was written against —
it is quoted throughout the existing `responses-api-compat` requirements and it is
what the parser in `previous_response_id_from_not_found_message` extracts an id
from. `Invalid \`previous_response_id\`.` carries no id at all.

Chasing the exact upstream taxonomy is not worth doing, because the distinction
does not change what this proxy should do. Both messages say the anchor cannot be
used. The proxy holds the client's full untrimmed body for exactly this case. The
correct response to either is to drop the anchor and send that body.

That is why the fix widens the predicate rather than adding a second branch: a
second branch would imply the two cases are handled differently, and they are not.

## Why `param` stops being required

`is_previous_response_not_found_error` required `param == "previous_response_id"`
before it would even look at the message. Upstream is not obliged to populate
`param`, and a message that names the field is not made ambiguous by its absence.

The requirement is relaxed rather than removed. An `invalid_request_error` that
names a *different* `param` is still not an anchor rejection, so a genuinely
malformed unrelated field cannot be swept into the continuity path.

## On over-matching

The widened predicate will also catch a client that supplies a syntactically bad
`previous_response_id` of its own. That client currently receives a 400; after
this change it receives a served response, because the recovery drops the bad
anchor and replays the full body.

This is the better outcome, and it is bounded. The replay only happens when a
self-contained full body is available to replay — `fresh_upstream_request_is_retry_safe`
is false for a payload carrying only incremental tool outputs, and the existing
requirements already forbid replaying those as a fresh turn. Where no such body
exists, the error is still surfaced, now as the retryable `stream_incomplete`
continuity failure the spec already mandates rather than as a raw upstream 400.

## Naming

The predicates keep the name `..._not_found_...` while now classifying a broader
condition. `previous_response_not_found` is a real upstream error code and the
name is load-bearing across the existing requirements, the public-error masking,
and the HTTP bridge rebind path. Renaming it would touch every one of those for
no behavioural gain. The docstrings carry the widened meaning instead.

## Left open: which response becomes the anchor

At 11:18:01Z the same session completed `resp_08f0604e…` successfully. At
11:25:49Z the proxy still pinned the 11:04 anchor. A newer completed response in
the same session did not displace an older one that upstream had already rejected
four times.

Two things are wrong there and neither is fixed here: the anchor selection prefers
a response it should have moved past, and a rejected anchor is never marked as
rejected, so nothing stops it being chosen again. Fixing the classifier makes each
individual turn recover, which is what unblocks the operator. It does not stop the
proxy re-pinning a dead anchor and paying for a replay on every turn. That belongs
in its own change against the continuity-state selection.

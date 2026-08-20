## ADDED Requirements

### Requirement: An upstream anchor rejection is classified by condition, not by wording

The service MUST classify an upstream error as a continuity-anchor rejection when
the upstream refuses the `previous_response_id` the request carried, regardless of
which wording upstream used to refuse it. At minimum, an error MUST be classified
as an anchor rejection when it carries the code `previous_response_not_found`, and
when it carries the code or type `invalid_request_error` together with a message
that either states the previous response was not found or names
`previous_response_id` as invalid.

Classification MUST NOT depend on upstream populating `param`. An
`invalid_request_error` whose message itself names `previous_response_id` MUST be
classified as an anchor rejection when `param` is absent. An error whose `param`
names a different field MUST NOT be classified as an anchor rejection.

Every requirement in this capability that governs a `previous_response_not_found`
continuity miss — the WebSocket full-resend replay, the HTTP bridge rebind, and
the masking of the error from public payloads — applies to the classified
condition, not to any one upstream sentence.

An anchor rejection that carries no response id in its message MUST still be
classified. Extraction of the missing response id MUST remain optional, and its
absence MUST NOT prevent recovery.

#### Scenario: Upstream refuses the anchor without saying "not found"

- **WHEN** upstream returns `invalid_request_error` with the message ``Invalid `previous_response_id`.``
- **THEN** the service classifies it as a continuity-anchor rejection
- **AND** it does so whether or not upstream set `param` to `previous_response_id`
- **AND** no missing response id is extracted from that message
- **AND** the raw upstream invalid-request error is not forwarded to the client

#### Scenario: Upstream names the missing response

- **WHEN** upstream returns `invalid_request_error` with `param=previous_response_id` and a message saying the previous response with a given id was not found
- **THEN** the service classifies it as a continuity-anchor rejection
- **AND** the missing response id is extracted from the message

#### Scenario: An unrelated invalid request is not an anchor rejection

- **WHEN** upstream returns `invalid_request_error` naming a `param` other than `previous_response_id`
- **OR** it returns `invalid_request_error` with a message that does not name `previous_response_id` and does not say a previous response was not found
- **THEN** the service MUST NOT classify it as a continuity-anchor rejection
- **AND** the error is handled as an ordinary invalid request

### Requirement: A proxy-injected anchor rejection is recovered without the client's involvement

When the service injects a `previous_response_id` the client did not send in order
to trim the input it forwards upstream, and upstream then rejects that anchor, the
service MUST recover the turn itself. It MUST NOT surface an error about an anchor
the client never chose and cannot clear.

Recovery MUST use the untrimmed client payload the service retained when it
injected the anchor: the service MUST reconnect, replay that payload as a fresh
turn without `previous_response_id`, and deliver the resulting response events
downstream. Where the retained payload is not a self-contained fresh turn, the
service MUST emit the retryable continuity failure instead, and MUST NOT fabricate
a fresh turn from an incremental payload.

#### Scenario: Injected anchor is rejected mid-session

- **WHEN** a Codex WebSocket session's `response.create` carried a `previous_response_id` injected by the service rather than by the client
- **AND** upstream rejects that anchor before assigning a response id
- **AND** the service retained the client's untrimmed payload as a self-contained fresh turn
- **THEN** the service reconnects and replays the untrimmed payload without `previous_response_id`
- **AND** the client receives the recovered response events
- **AND** the client does not receive an error naming `previous_response_id`

#### Scenario: Injected anchor is rejected with no replayable body

- **WHEN** a Codex WebSocket session's `response.create` carried a service-injected `previous_response_id`
- **AND** upstream rejects that anchor
- **AND** the retained payload is not a self-contained fresh turn
- **THEN** the service MUST NOT replay it as a fresh turn
- **AND** the client receives a retryable continuity failure rather than the raw upstream invalid-request error

## MODIFIED Requirements

### Requirement: WebSocket full-resend previous-response misses retry without stale anchor

When a direct WebSocket `response.create` request includes both `previous_response_id` and a self-contained full resend payload, the service MUST retain a safe replay body without `previous_response_id`. If upstream rejects the anchor before `response.created` — with `previous_response_not_found` or with any other wording classified as a continuity-anchor rejection — the service MUST reconnect and replay the retained full payload as a fresh turn instead of forwarding the raw upstream invalid-request error. A payload that only carries incremental tool outputs for tool calls that are not also present in the same request is not self-contained and MUST NOT be replayed as a fresh turn without `previous_response_id`.

#### Scenario: full-resend WebSocket follow-up loses just-completed anchor
- **WHEN** a WebSocket `/v1/responses` or `/backend-api/codex/responses` follow-up has `previous_response_id`
- **AND** the request payload also carries enough input to be treated as a full resend
- **AND** upstream rejects the anchor before assigning a response id
- **THEN** the service reconnects the upstream WebSocket
- **AND** it replays the same request without `previous_response_id`
- **AND** the downstream client receives the recovered response events, not the raw upstream error

#### Scenario: output-only WebSocket tool delta is not replayed as a fresh turn
- **WHEN** a WebSocket `/v1/responses` or `/backend-api/codex/responses` follow-up has `previous_response_id`
- **AND** the request payload carries `function_call_output`, `custom_tool_call_output`, or `apply_patch_call_output` items without their matching tool-call items in the same payload
- **AND** upstream rejects the anchor before assigning a response id
- **THEN** the service MUST NOT replay that payload as a fresh turn without `previous_response_id`
- **AND** the downstream client receives a retryable continuity failure rather than a fabricated fresh turn

### Requirement: Public Responses errors mask previous-response misses

Public Responses endpoints MUST NOT return an OpenAI-shaped `previous_response_not_found` error, or any other upstream continuity-anchor rejection, to clients. If a lower layer still raises or collects that error, the API layer MUST rewrite it to a retryable `stream_incomplete` continuity failure and remove the missing response id from the public payload.

#### Scenario: API layer receives an upstream previous-response miss
- **WHEN** a public `/responses`, `/v1/responses`, `/responses/compact`, or `/v1/responses/compact` handler receives an error with `code=previous_response_not_found`
- **OR** it receives `code=invalid_request_error` with a message saying the previous response was not found
- **OR** it receives `code=invalid_request_error` with a message naming `previous_response_id` as invalid
- **THEN** the response status is retryable
- **AND** the public error code is `stream_incomplete`
- **AND** the missing `previous_response_id` is not exposed in the response body

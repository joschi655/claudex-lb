# anthropic-provider

## ADDED Requirements

### Requirement: Relayed completions are recorded in request logs

Every upstream attempt the Anthropic relay makes against a selected account for
`POST /v1/messages` SHALL produce exactly one `request_logs` row.

The row SHALL carry the selected account's id, the model named in the client request
body, the proxy API key id that authenticated the request, the client user agent and its
derived group, the client IP, and the total latency of the attempt in milliseconds.

`POST /v1/messages/count_tokens` SHALL NOT be logged. It returns no completion and
consumes no quota, and logging it would distort per-request aggregates.

#### Scenario: A successful non-streaming completion is logged

- **WHEN** the relay returns a `200` JSON response from account `A`
- **THEN** exactly one `request_logs` row exists for account `A` with status `success`
  and a non-null `latency_ms`

#### Scenario: A token count is not logged

- **WHEN** the relay serves `POST /v1/messages/count_tokens` successfully
- **THEN** no `request_logs` row is written for that request

### Requirement: Token usage is extracted from both response shapes

The relay SHALL record token counts for successful completions.

For a non-streaming response, counts SHALL be read from the `usage` object of the
response body. For a streaming response, the input counts and the model SHALL be read
from the `message_start` event and the output count from the last `message_delta` event
carrying one.

Extraction SHALL NOT buffer the response body, and SHALL NOT delay delivery of any chunk
to the client.

When a response's usage cannot be parsed, the row SHALL still be written with null token
counts rather than omitted.

#### Scenario: Streaming usage is captured without buffering

- **WHEN** the relay streams a response whose `message_start` reports 100 input tokens
  and whose final `message_delta` reports 250 output tokens
- **THEN** the logged row records 100 input tokens and 250 output tokens
- **AND** every chunk was forwarded to the client as it arrived

#### Scenario: Unparseable usage still yields a row

- **WHEN** a successful response body cannot be parsed as Messages API JSON
- **THEN** a row is written with status `success` and null token counts

### Requirement: Anthropic input counters map to total-and-subset columns

Anthropic reports `input_tokens` exclusive of cached tokens, alongside separate
`cache_read_input_tokens` and `cache_creation_input_tokens`. The cost path in this
project treats `cached_input_tokens` as a **subset** of `input_tokens`.

The relay SHALL therefore record `input_tokens` as the sum of the uncached input, the
cache reads, and the cache writes, and `cached_input_tokens` as the cache reads alone.

#### Scenario: Split counters are normalized

- **WHEN** a response reports `input_tokens=10`, `cache_read_input_tokens=90`, and
  `cache_creation_input_tokens=5`
- **THEN** the logged row records `input_tokens=105` and `cached_input_tokens=90`

### Requirement: Every failover attempt is logged separately

When the relay fails over between accounts, each attempt that reached an upstream
response SHALL produce its own row, recording that attempt's account, its status
`error`, an error code, and the upstream HTTP status code.

An attempt that never reached an upstream response — an account dropped by a failed
token refresh before any request was sent — SHALL NOT produce a row, because no upstream
attempt occurred.

#### Scenario: A rate-limited account and its successor are both visible

- **WHEN** account `A` returns `429` and the relay succeeds on account `B`
- **THEN** one row exists for `A` with status `error`, error code `rate_limit_exceeded`,
  and upstream status code `429`
- **AND** one row exists for `B` with status `success`

### Requirement: Logging is off the response path and never fails a request

Request-log writes SHALL be performed on background tasks that are tracked for the
lifetime of the process so they are neither garbage-collected mid-flight nor able to
delay the client response.

A failure to write a request log SHALL be logged as a warning and otherwise ignored; it
SHALL NOT change the response the client receives.

#### Scenario: A database failure does not surface to the client

- **WHEN** the request-log write raises
- **THEN** the client still receives the upstream response unchanged

### Requirement: Subscription requests carry no synthesized cost

The relay SHALL NOT populate `cost_usd` for models with no pricing entry. A Claude
subscription seat has no marginal per-request price, and recording a list-price estimate
would present a charge that was never incurred.

#### Scenario: A Claude completion records no cost

- **WHEN** a Claude model completes successfully through the relay
- **THEN** the logged row's `cost_usd` is null

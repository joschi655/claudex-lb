# anthropic-provider Specification Delta

## MODIFIED Requirements

### Requirement: Anthropic usage state is polled independently of served traffic

The proxy SHALL poll `GET https://api.anthropic.com/api/oauth/usage` for each Anthropic
account holding an OAuth credential, on the cadence already governed by
`CODEX_LB_USAGE_REFRESH_ENABLED` and `CODEX_LB_USAGE_REFRESH_INTERVAL_SECONDS`. The
request SHALL carry the account's bearer token and the `oauth-2025-04-20` beta flag.
Reported five-hour and seven-day utilizations SHALL be persisted through the same
usage-history contract that response-header ingestion uses, so an account that is serving
no traffic still converges on its true quota state.

The poll SHALL be authoritative for the windows it reports: a polled value replaces the
stored sample for that window rather than being merged with or discarded in favour of it.

Accounts whose credential is a static API key SHALL be skipped, because the endpoint is
scoped to subscription OAuth credentials and a console key has no window state to report.

#### Scenario: An idle account's windows refresh without serving a request

- **WHEN** an Anthropic account has served no request since its last usage sample
- **AND** the refresh loop polls the usage API
- **THEN** the account's primary and secondary usage rows reflect the polled utilizations
  and reset timestamps

#### Scenario: A stale sample is corrected

- **GIVEN** an account's stored five-hour sample reads 1% while the usage API reports 100%
- **WHEN** the poll runs
- **THEN** the stored sample is replaced by 100%
- **AND** the load balancer no longer treats the account as having free quota

#### Scenario: Static API-key accounts are not polled

- **WHEN** an Anthropic account's credential is a static API key
- **THEN** no usage-API request is made for it

### Requirement: The usage poll never degrades the loop it shares

A failed usage poll SHALL NOT change account status, abort the OpenAI usage refresh, or
prevent limit warmup from running in the same tick. HTTP 429 from the usage endpoint
SHALL place that account's poll in a cooldown and SHALL NOT be treated as an account
fault, because the endpoint throttles aggressively and other clients on the same account
consume the same budget.

#### Scenario: Throttled poll backs off without touching the account

- **WHEN** the usage endpoint answers 429 for an account
- **THEN** that account is not polled again until its cooldown elapses
- **AND** the account's status is unchanged

#### Scenario: A failing poll does not stop warmup

- **WHEN** the usage poll raises for one account
- **THEN** the remaining accounts are still polled
- **AND** limit warmup still runs in the same tick

### Requirement: A window reported as not running is warmable

The usage API reports a five-hour window that has run out as `utilization: 0` with a null
`resets_at`. An account in that state SHALL be treated as having an elapsed window for the
purposes of limit warmup, so a ping opens a fresh one. An account that reports no
five-hour window at all — a usage-based seat — SHALL remain excluded, because there is no
window for a ping to open.

#### Scenario: A spent window with no reset is warmed

- **GIVEN** an account whose stored five-hour row carries no reset timestamp
- **WHEN** the warmup pass evaluates it
- **THEN** it is a warmup candidate

#### Scenario: A usage-based seat is still never warmed

- **WHEN** an account has no five-hour usage row at all
- **THEN** it is not a warmup candidate

### Requirement: Unchanged polls are not rewritten every tick

A polled snapshot identical to the one last written for that account SHALL NOT be
persisted again until a minimum interval has elapsed, so an idle account does not append
an identical row on every tick. A snapshot that differs SHALL be written immediately —
the throttle applies only to restating what is already stored.

#### Scenario: An idle account is not rewritten each tick

- **WHEN** consecutive polls report the same utilizations and reset timestamps
- **THEN** at most one row set is written until the minimum interval elapses

#### Scenario: A change is written without delay

- **WHEN** a poll reports a utilization or reset that differs from the stored row
- **THEN** the write happens on that tick

#### Scenario: An unchanged account is refreshed once the interval elapses

- **WHEN** the minimum interval passes with the snapshot still unchanged
- **THEN** the row is written again, so its recency continues to reflect that the account
  is still reporting

## ADDED Requirements

### Requirement: Usage-based seats expose a spend budget

Some Anthropic seats bill against a dollar budget and report no rolling window: their
usage payload carries `five_hour: null` and `seven_day: null` alongside a bucket
describing dollars. The proxy SHALL record such a bucket as a `budget` usage window
carrying the bucket's utilization percentage and reset timestamp, and SHALL expose the
dollar figures — used, limit, remaining, and currency — on the account summary so a seat
with no window is not presented as having no quota information.

Bucket keys SHALL NOT be hardcoded. The payload names these buckets with rotating code
words, so any top-level object carrying a non-null `limit_dollars` SHALL be treated as the
budget bucket. When the payload also reports enabled extra-usage credits, the credit
figures SHALL be exposed alongside the budget.

#### Scenario: A dollar-budget seat reports its budget

- **GIVEN** a usage payload with `five_hour: null`, `seven_day: null`, and a bucket
  carrying `limit_dollars: 1000`, `used_dollars: 777.24`, `remaining_dollars: 222.76`
- **WHEN** the poll persists it
- **THEN** a `budget` usage row records 77.7% used with the bucket's reset timestamp
- **AND** the account summary reports used, limit, and remaining dollars in the bucket's
  currency

#### Scenario: A bucket under an unrecognized key is still read

- **WHEN** the dollar bucket appears under a key the code has never seen
- **THEN** it is still recognized as the budget, because recognition is by the presence of
  `limit_dollars` rather than by key name

#### Scenario: A subscription seat reports no budget

- **WHEN** a payload's dollar fields are all null
- **THEN** no `budget` row is written
- **AND** the account summary carries no spend block

#### Scenario: Extra usage credits are surfaced when enabled

- **WHEN** a payload reports extra usage as enabled with a used and limit amount
- **THEN** the account summary exposes those credit figures

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

## ADDED Requirements

### Requirement: Request logs persist the serving account's provider

Every `request_logs` row MUST record the provider of the account that served the attempt.
The value MUST be resolved from the serving account at write time and stored on the row,
so it survives deletion of that account. When a row has no serving account, the provider
MUST be persisted as `null`.

#### Scenario: Row written for a Claude account records the Anthropic provider

- **WHEN** a request is served by an account whose provider is `anthropic`
- **THEN** the persisted `request_logs` row stores `provider = "anthropic"`

#### Scenario: Row written for a ChatGPT account records the OpenAI provider

- **WHEN** a request is served by an account whose provider is `openai`
- **THEN** the persisted `request_logs` row stores `provider = "openai"`

#### Scenario: Provider survives deletion of the serving account

- **WHEN** a `request_logs` row was written for an account whose provider is `anthropic`
- **AND** that account is subsequently deleted, clearing the row's `account_id`
- **THEN** the row still reports `provider = "anthropic"`

#### Scenario: Row without a serving account has no provider

- **WHEN** a `request_logs` row is written with no `account_id`
- **THEN** the persisted row stores `provider = null`

### Requirement: Existing request-log rows are backfilled with a provider

The migration that introduces `request_logs.provider` MUST backfill existing rows from
their serving account's provider where that account still exists, and MUST leave rows
with no resolvable account at `openai` so pre-existing statistics keep their meaning.

#### Scenario: Historical row is backfilled from its account

- **WHEN** the migration runs against a database containing a `request_logs` row whose
  account has provider `anthropic`
- **THEN** the row's `provider` is set to `anthropic`

#### Scenario: Orphaned historical row defaults to OpenAI

- **WHEN** the migration runs against a database containing a `request_logs` row whose
  `account_id` is null or references no existing account
- **THEN** the row's `provider` is set to `openai`

### Requirement: Request-log listing supports provider filtering

The request-log listing endpoint MUST accept a repeatable provider filter and MUST return
only rows whose persisted provider matches one of the requested values. When no provider
filter is supplied, rows of every provider MUST be returned. Each returned entry MUST
expose its provider.

#### Scenario: Filtering to one provider excludes the other

- **WHEN** the request log contains rows with `provider = "anthropic"` and rows with
  `provider = "openai"`
- **AND** the operator lists request logs filtered to provider `anthropic`
- **THEN** only the `anthropic` rows are returned

#### Scenario: Unfiltered listing returns every provider

- **WHEN** the operator lists request logs without a provider filter
- **THEN** rows of every provider are returned

#### Scenario: Listed entries expose their provider

- **WHEN** the operator lists request logs
- **THEN** each returned entry includes the provider persisted on its row

### Requirement: Request-log filter options report available providers

The request-log filter-options endpoint MUST report the distinct providers present among
the rows matching the other active filters, so the dashboard can offer only providers that
have traffic.

#### Scenario: Options list the providers present in the log

- **WHEN** the request log contains rows with `provider = "anthropic"` and rows with
  `provider = "openai"`
- **THEN** the filter options report both providers

#### Scenario: Single-provider pool offers a single provider

- **WHEN** every row in the request log has `provider = "openai"`
- **THEN** the filter options report only `openai`

### Requirement: Daily reports support provider filtering

The daily reports endpoint MUST accept a provider filter and MUST restrict every
aggregate it computes — daily cost, tokens, request counts, latency, and the model and
user-agent distributions — to rows whose persisted provider matches. When no provider
filter is supplied, the aggregates MUST cover every provider.

#### Scenario: Reports scoped to one provider exclude the other's rows

- **WHEN** the request log contains rows for both providers on the same day
- **AND** the operator requests reports filtered to provider `anthropic`
- **THEN** every returned aggregate reflects only the `anthropic` rows

#### Scenario: Unfiltered reports cover the whole pool

- **WHEN** the operator requests reports without a provider filter
- **THEN** the returned aggregates reflect rows of every provider

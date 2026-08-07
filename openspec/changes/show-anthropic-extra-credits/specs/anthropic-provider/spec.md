# anthropic-provider Specification Delta

## ADDED Requirements

### Requirement: Usage ingestion persists the extra-usage pool

A polled usage snapshot that reports an extra-usage pool MUST be persisted as an
`extra_credits` usage window, separately from the seat's own `budget` window so that an
account reporting both keeps both. The row MUST carry whether the facility is enabled,
the pool's limit, and its remainder. The amount spent MUST be derived from the limit and
the remainder rather than stored as a third figure, so the three can never disagree.

A snapshot that reports the pool as switched off MUST still be persisted: the disabled
state is the state an operator acts on.

#### Scenario: An enabled pool is written with its dollars

- **GIVEN** a usage payload reporting extra usage as enabled with a limit and an amount used
- **WHEN** the poll persists the snapshot
- **THEN** an `extra_credits` row records the enabled state, the limit, and the remainder,
  and its utilization matches the utilization the payload itself reports

#### Scenario: A disabled pool is recorded rather than dropped

- **GIVEN** a usage payload reporting extra usage as disabled
- **WHEN** the poll persists the snapshot
- **THEN** an `extra_credits` row is written recording the facility as not enabled

#### Scenario: A pool alone is not an empty snapshot

- **GIVEN** a usage payload that reports an extra-usage pool and no window and no budget
- **WHEN** the poll evaluates the snapshot
- **THEN** the snapshot is treated as carrying usage and is written

### Requirement: Unchanged-write suppression accounts for extra-usage spend

The poller's suppression of unchanged writes MUST take the extra-usage pool into account.
Overflow spend moves independently of the rolling windows, so a snapshot whose windows are
unchanged but whose pool has moved MUST be written rather than suppressed.

#### Scenario: Moving overflow spend is not suppressed

- **GIVEN** an account whose last stored snapshot is within the unchanged-write interval
- **WHEN** a poll returns identical window figures but a different extra-usage spend
- **THEN** the snapshot is written rather than skipped as unchanged

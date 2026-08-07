## ADDED Requirements

### Requirement: Recent serving activity on the account summary

The account summary SHALL report when an account most recently carried a
request, as `last_served_at`. The lookup SHALL be bounded to a recent window
rather than the account's whole history, and an account with no request inside
that window SHALL report `null`.

`null` therefore means "not recently", not "never" — a summary field alone
cannot distinguish an account that has never served from one that last served
yesterday, and callers MUST NOT read it as a lifetime record.

Requests that were logged without an account — a request that failed before
selection — SHALL NOT contribute to any account's value.

#### Scenario: An account that just served reports its most recent request

- **GIVEN** an account with two requests inside the window
- **WHEN** the account summary is built
- **THEN** `last_served_at` is the newer of the two

#### Scenario: An idle account reports nothing

- **GIVEN** an account whose most recent request predates the window
- **WHEN** the account summary is built
- **THEN** `last_served_at` is `null`

#### Scenario: An unattributed request names no account

- **GIVEN** a request log row with no account id
- **WHEN** the lookup runs
- **THEN** no account's `last_served_at` reflects that row

### Requirement: Pace gates are editable from the dashboard

The dashboard account view SHALL render the account's three pace gates and allow
an operator to change each one. An empty field SHALL mean the gate is unset, and
SHALL be distinguishable from a value of `0` — a margin of `0` gates exactly at
the pace line, while an unset margin never gates.

Each field SHALL be submitted independently, so writing one gate leaves the
others as stored.

#### Scenario: Setting one gate leaves the others alone

- **GIVEN** an account with no gates set
- **WHEN** an operator sets only the primary pace margin
- **THEN** the primary margin is stored
- **AND** the secondary margin and the pre-reset window remain unset

#### Scenario: Clearing a gate switches it off

- **GIVEN** an account with a pre-reset window set
- **WHEN** an operator empties that field
- **THEN** the gate is cleared rather than set to zero

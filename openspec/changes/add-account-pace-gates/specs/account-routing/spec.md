## ADDED Requirements

### Requirement: Per-account usage pace gates

An account MAY carry an optional pace margin for the primary (short) window and for
the secondary (weekly) window. When a margin is set, the account MUST be excluded from
the selection pool unless its recorded usage in that window sits at least the margin
below the window's even-pace line.

The even-pace line for a window MUST be computed as
`expected_pct = 100 * elapsed / length`, where `length` is the window duration and
`elapsed` is `length - (reset_at - now)` clamped to `[0, length]`. The gate is
satisfied when `used_pct <= expected_pct - margin`. Absent usage MUST be treated as
`0`.

Margins MUST be accepted only in the inclusive range `0`–`100`.

#### Scenario: Account below the pace line is selectable

- **GIVEN** an account with `pace_margin_secondary_pct` of `20`
- **AND** its weekly window is half elapsed, giving an even-pace line of `50%`
- **AND** its recorded weekly usage is `25%`
- **THEN** the account remains in the selection pool

#### Scenario: Account ahead of the pace line is excluded

- **GIVEN** an account with `pace_margin_secondary_pct` of `20`
- **AND** its weekly window is half elapsed, giving an even-pace line of `50%`
- **AND** its recorded weekly usage is `35%`
- **THEN** the account is excluded from the selection pool
- **AND** the exclusion is reported as a pace-gate exclusion, not as an error state

#### Scenario: Margin of zero gates exactly at the pace line

- **GIVEN** an account with `pace_margin_primary_pct` of `0`
- **AND** its short window is one quarter elapsed, giving an even-pace line of `25%`
- **WHEN** its recorded short-window usage is `25%`
- **THEN** the account remains in the selection pool
- **AND** at `26%` it is excluded

#### Scenario: Margin outside the accepted range is rejected

- **WHEN** an operator submits a pace margin below `0` or above `100`
- **THEN** the request is rejected with a validation error
- **AND** the stored account configuration is unchanged

### Requirement: Pre-reset window gate

An account MAY carry an optional `pre_reset_window_minutes`. When set, the account
MUST be excluded from the selection pool unless its primary-window reset is at most
that many minutes away.

#### Scenario: Account inside the pre-reset window is selectable

- **GIVEN** an account with `pre_reset_window_minutes` of `120`
- **AND** its primary window resets in 90 minutes
- **THEN** the account remains in the selection pool

#### Scenario: Account outside the pre-reset window is excluded

- **GIVEN** an account with `pre_reset_window_minutes` of `120`
- **AND** its primary window resets in 200 minutes
- **THEN** the account is excluded from the selection pool

### Requirement: Pace gates combine conjunctively

When more than one gate is configured on an account, the account MUST satisfy every
configured gate to remain selectable. A gate that is not configured MUST NOT affect
eligibility.

#### Scenario: One failing gate excludes the account

- **GIVEN** an account configured with all three gates
- **AND** it satisfies the pre-reset window and the primary pace margin
- **AND** it fails the secondary pace margin
- **THEN** the account is excluded from the selection pool

### Requirement: Pace gates are hard eligibility filters

An account excluded by a pace gate MUST NOT be reachable through any later
selection tier, including budget-safe fallback, backoff fallback, and routing-policy
preference. A `burn_first` policy MUST NOT re-admit a gated-out account.

When every candidate is excluded by pace gates, selection MUST fail with an error that
identifies pace gating as the cause, rather than silently falling back to a gated
account.

#### Scenario: Burn-first does not bypass a gate

- **GIVEN** an account with routing policy `burn_first`
- **AND** a configured pace gate that the account currently fails
- **THEN** the account is not selected
- **AND** selection proceeds among the remaining eligible accounts

#### Scenario: All accounts gated out reports the cause

- **GIVEN** every candidate account fails at least one configured pace gate
- **WHEN** an account is requested
- **THEN** selection returns no account
- **AND** the error message identifies pace gating as the reason

### Requirement: Pace gates do not apply without window bounds

A pace gate MUST NOT exclude an account when the window bounds required to compute its
even-pace line are unavailable — that is, when the window's reset timestamp or its
duration is unknown. The pre-reset window gate MUST NOT exclude an account when the
primary reset timestamp is unknown.

#### Scenario: Freshly imported account is not stranded

- **GIVEN** an account that has served no traffic and therefore has no recorded window
  reset timestamp
- **AND** a configured primary pace margin
- **THEN** the pace gate does not exclude the account
- **AND** the account remains subject to all other eligibility gates

### Requirement: Pace gate configuration is exposed on the account API

The dashboard account API MUST accept and return `pace_margin_primary_pct`,
`pace_margin_secondary_pct`, and `pre_reset_window_minutes`, each nullable, and MUST
treat an omitted field as "leave unchanged" on update.

#### Scenario: Operator clears a gate

- **GIVEN** an account with `pace_margin_primary_pct` set to `20`
- **WHEN** the operator updates the account with `pace_margin_primary_pct` explicitly
  set to null
- **THEN** the gate is cleared
- **AND** the account is no longer excluded by that gate

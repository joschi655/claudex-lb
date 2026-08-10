# anthropic-provider

## MODIFIED Requirements

### Requirement: A closed window stays warmable

An account whose window reports no reset timestamp SHALL remain a warmup candidate on
every evaluation, not only the first one. The record kept to prevent duplicate attempts
SHALL identify the closed-window state as observed within a bounded period, so that
concurrent evaluators collapse to one attempt while a later evaluation is free to try
again.

An attempt that never reached a terminal status SHALL NOT prevent later attempts
indefinitely.

#### Scenario: A closed window is warmed again in a later period

- **GIVEN** an enabled Anthropic account whose window reports no reset timestamp
- **AND** it was warmed for that state already
- **WHEN** the warmup pass evaluates it again after the cooldown has elapsed
- **THEN** a further warmup is sent

#### Scenario: Repeated evaluations inside one period send one ping

- **GIVEN** an enabled Anthropic account whose window reports no reset timestamp
- **WHEN** the warmup pass evaluates it twice within the same period
- **THEN** exactly one warmup is sent

#### Scenario: A stale in-flight attempt does not lock the account out

- **GIVEN** a warmup attempt for an account that was never completed
- **WHEN** the warmup pass evaluates that account's closed window in a later period
- **THEN** a warmup is sent

### Requirement: The warmup cooldown applies per window

The cooldown between warmups SHALL be evaluated for the window a warmup is being sent
for, not for the account as a whole. An account's five-hour and weekly windows close on
independent schedules, so a warmup sent for one SHALL NOT delay a warmup that the other
window becomes due for.

The candidate window SHALL be selected before the cooldown is consulted, so that an
account whose five-hour window is closed continues to be evaluated against the five-hour
cooldown rather than falling through to the weekly window.

#### Scenario: A weekly ping does not delay the next five-hour ping

- **GIVEN** an account warmed because its weekly window closed
- **WHEN** its five-hour window runs out while that warmup is still inside the cooldown
- **THEN** a warmup is sent for the five-hour window

#### Scenario: A failed ping is not retried against the other window

- **GIVEN** an account whose five-hour and weekly windows are both closed
- **AND** a warmup for it failed within the cooldown
- **WHEN** the warmup pass evaluates it again inside that cooldown
- **THEN** no further warmup is sent

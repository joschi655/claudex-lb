# live-usage-ingestion

## MODIFIED Requirements

### Requirement: Unified rate-limit utilization is read as a fraction

The `anthropic-ratelimit-unified-*-utilization` response headers report a fraction of
the window. Ingestion SHALL convert that fraction to a percentage and SHALL NOT treat
any value as being already expressed as a percentage.

Utilization SHALL be permitted to exceed 1. A value above 1 describes a window that has
been used past its limit and SHALL be recorded as fully spent, never as a low
percentage. The recorded percentage SHALL be clamped to 100.

A missing or unparseable header SHALL continue to yield no value for that window rather
than an error.

#### Scenario: A fraction becomes a percentage

- **WHEN** a response carries a five-hour utilization header of `0.42`
- **THEN** the account's five-hour window is recorded as 42% used

#### Scenario: An over-limit fraction is recorded as spent

- **WHEN** a response carries a five-hour utilization header of `1.04`
- **THEN** the account's five-hour window is recorded as 100% used

#### Scenario: A rejected request does not mark its account healthy

- **GIVEN** an account whose window is spent
- **WHEN** its request is rejected with a rate-limit error carrying a utilization header
  above 1
- **THEN** the account's window is recorded as fully spent

#### Scenario: An unreadable header changes nothing

- **WHEN** a response carries a utilization header that is not a number
- **THEN** no utilization is recorded for that window

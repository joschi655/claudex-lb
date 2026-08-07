# anthropic-provider

## MODIFIED Requirements

### Requirement: An elapsed rolling window triggers a warmup

An Anthropic account's warmup eligibility SHALL be evaluated from its stored window state.

Both of a Claude subscription seat's rolling windows — the five-hour window and the weekly
window — are anchored to the account's first request rather than to a calendar, so either
can sit closed while the account is idle. Each SHALL be evaluated for warmup on its own
terms: a window whose recorded reset timestamp has passed, or which is on record with no
reset timestamp at all, SHALL make the account a warmup candidate, subject to the
enablement rules above and to the existing warmup cooldown.

A window whose recorded reset timestamp is still in the future SHALL NOT make the account
a candidate. The five-hour window being live SHALL NOT suppress evaluation of the weekly
window.

#### Scenario: An idle account is warmed once its five-hour window closes

- **WHEN** an enabled Anthropic account's recorded five-hour reset timestamp is in the
  past
- **THEN** a warmup is sent for that account

#### Scenario: A closed weekly window is warmed while the five-hour window runs

- **GIVEN** an enabled Anthropic account whose five-hour reset timestamp is in the future
- **WHEN** its weekly window is on record with no reset timestamp
- **THEN** a warmup is sent for that account

#### Scenario: An elapsed weekly reset is warmed

- **GIVEN** an enabled Anthropic account whose five-hour reset timestamp is in the future
- **WHEN** its recorded weekly reset timestamp is in the past
- **THEN** a warmup is sent for that account

#### Scenario: An account inside both windows is left alone

- **WHEN** an enabled Anthropic account's recorded five-hour and weekly reset timestamps
  are both in the future
- **THEN** no warmup is sent for that account

#### Scenario: The cooldown prevents repeated pings

- **WHEN** an account was warmed within the configured cooldown
- **THEN** it is not warmed again until the cooldown elapses

### Requirement: One ping covers every window it opens

A single warmup request opens every closed window on the account, so an account with more
than one closed window SHALL be sent exactly one ping per evaluation. The five-hour window
SHALL take precedence when both are closed, and the attempt SHALL be recorded against the
window it was chosen for so it dedupes against that window's state.

#### Scenario: Two closed windows cost one ping

- **GIVEN** an enabled Anthropic account whose five-hour and weekly windows are both
  closed
- **WHEN** the warmup pass evaluates it
- **THEN** exactly one warmup is sent
- **AND** the attempt is recorded against the five-hour window

#### Scenario: A weekly attempt is recorded under its own window

- **WHEN** an account is warmed because its weekly window is closed
- **THEN** the attempt is recorded against the weekly window rather than the five-hour one

### Requirement: Accounts without a rolling window are never warmed

An account that reports no rolling window — a usage-based seat that bills against a budget
rather than a window — SHALL be excluded from warmup. There is no window to open, so a
ping would spend budget for no benefit.

The absence of a window SHALL be read from the absence of a stored row for it. A row that
carries no reset timestamp describes a window that has run out, which is the state warmup
exists to leave, and SHALL NOT be read as the account having no window.

#### Scenario: A usage-based seat is skipped

- **WHEN** an Anthropic account has never recorded a five-hour or weekly window
- **THEN** warmup does not send a request for it

#### Scenario: A seat with no weekly window is not warmed for one

- **GIVEN** an Anthropic account whose five-hour reset timestamp is in the future
- **WHEN** it has no weekly window on record
- **THEN** warmup does not send a request for it

### Requirement: Warmup can be triggered on demand for one account

An operator SHALL be able to open a window for a single Anthropic account on demand,
independently of the scheduled-warmup setting, so a window can be opened by hand without
turning on automatic warmup.

The request SHALL be refused for an account that cannot be warmed — a non-Anthropic
account, a status that can never serve again, or a seat with no rolling window on
record — with a client error rather than by spending a ping.

Eligibility SHALL be decided by whether a rolling window is on record, not by whether one
is currently running. Either the five-hour or the weekly window on record SHALL satisfy
the gate, and an account whose only recorded window has run out SHALL be warmable.

#### Scenario: An operator opens a window on demand

- **WHEN** a warmup is triggered for an eligible Anthropic account
- **THEN** one warmup request is sent for that account
- **AND** the result reports whether it succeeded

#### Scenario: An account whose window has run out is warmable

- **GIVEN** an Anthropic account whose stored five-hour row carries no reset timestamp
- **WHEN** a warmup is triggered for it
- **THEN** the request is sent

#### Scenario: A weekly window on record satisfies the gate

- **GIVEN** an Anthropic account with a weekly window on record and no five-hour row
- **WHEN** a warmup is triggered for it
- **THEN** the request is sent

#### Scenario: A seat with no window is refused

- **WHEN** a warmup is triggered for an Anthropic account with no rolling window on record
- **THEN** the request is refused with a client error
- **AND** no warmup request is sent

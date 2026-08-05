# anthropic-provider

## ADDED Requirements

### Requirement: Claude accounts participate in limit warmup

Limit warmup SHALL select its upstream sender by the account's provider. An Anthropic
account SHALL be warmed with a `POST /v1/messages` request carrying `max_tokens: 1` and
a single minimal user message, addressed to a fixed low-cost Claude model, and
authenticated with that account's own OAuth credential through the same refresh path the
relay uses.

A warmup request SHALL be recorded as a warmup attempt and a request log entry in the
same way a Codex warmup is, so an operator can tell warmup traffic apart from served
traffic.

Warmup SHALL remain disabled by default. An Anthropic account SHALL be warmed only when
the global warmup setting and that account's own warmup toggle are both enabled.

#### Scenario: An Anthropic account is warmed with the Messages API

- **WHEN** limit warmup runs for an Anthropic account
- **THEN** the upstream request is a Messages API call bearing that account's credential
- **AND** no ChatGPT Responses request is made

#### Scenario: Warmup stays off unless enabled

- **WHEN** the global warmup setting is disabled
- **THEN** no Anthropic account is warmed, whatever its per-account toggle says

#### Scenario: A warmup attempt is distinguishable from served traffic

- **WHEN** an Anthropic warmup completes
- **THEN** its request log row is marked as warmup-sourced rather than as a relayed
  client request

### Requirement: An elapsed five-hour window triggers a warmup

An Anthropic account's warmup eligibility SHALL be evaluated from its stored window
state rather than from a usage poll, because Anthropic exposes no usage API to the
proxy.

When an account's recorded five-hour reset timestamp has passed, the account SHALL be
treated as having an elapsed window and warmed, subject to the enablement rules above
and to the existing warmup cooldown.

An account whose recorded reset timestamp is still in the future SHALL NOT be warmed by
the elapsed-window trigger.

#### Scenario: An idle account is warmed once its window closes

- **WHEN** an enabled Anthropic account's recorded five-hour reset timestamp is in the
  past
- **THEN** a warmup is sent for that account

#### Scenario: An account inside its window is left alone

- **WHEN** an enabled Anthropic account's recorded five-hour reset timestamp is in the
  future
- **THEN** no warmup is sent for that account

#### Scenario: The cooldown prevents repeated pings

- **WHEN** an account was warmed within the configured cooldown
- **THEN** it is not warmed again until the cooldown elapses

### Requirement: A paused Claude account is still warmed

Pausing an Anthropic account SHALL keep it out of request routing without stopping its
warmup: its five-hour window keeps ageing whether or not it serves, and an operator
parks an account precisely so it is available later. Both the scheduled sweep and the
on-demand trigger SHALL treat a paused Anthropic account as eligible.

This relaxation SHALL be Anthropic-only. A paused ChatGPT account SHALL continue to be
skipped, since that provider's warmup is not expected to emit traffic for a parked
account.

#### Scenario: The sweep warms a parked Claude account

- **WHEN** a paused Anthropic account's five-hour window has elapsed
- **THEN** a warmup is sent for it
- **AND** the account stays paused

#### Scenario: A paused ChatGPT account is left alone

- **WHEN** a paused OpenAI account's window has elapsed
- **THEN** no warmup is sent for it

### Requirement: Accounts without a five-hour window are never warmed

An account that reports no five-hour window — a usage-based seat that bills against a
budget rather than a rolling window — SHALL be excluded from warmup. There is no window
to open, so a ping would spend budget for no benefit.

#### Scenario: A usage-based seat is skipped

- **WHEN** an Anthropic account has never recorded a five-hour window
- **THEN** warmup does not send a request for it

### Requirement: A warmup response updates the account's window state

A warmup request's response SHALL be parsed for the unified rate-limit headers and
ingested as a usage snapshot for the warmed account, using the same ingestion path as a
relayed response.

The newly opened window SHALL therefore be visible without waiting for the account to
serve a real request.

#### Scenario: The new window is visible immediately

- **WHEN** a warmup succeeds and its response carries five-hour utilization and reset
  headers
- **THEN** the account's stored five-hour window reflects those values

#### Scenario: A response without usage headers is not fatal

- **WHEN** a warmup succeeds but its response carries no rate-limit headers
- **THEN** the attempt is still recorded as successful and no usage snapshot is written

### Requirement: Warmup failures do not change account health

A failed Anthropic warmup SHALL NOT by itself mark an account unhealthy, pause it, or
remove it from selection. The attempt SHALL be recorded with its error so the failure is
visible.

An authentication failure that the refresh path cannot repair SHALL be handled exactly as
it is for a relayed request, and SHALL NOT be given a warmup-specific outcome.

#### Scenario: A failed ping leaves the account selectable

- **WHEN** an Anthropic warmup request fails with an upstream error
- **THEN** the account's status is unchanged
- **AND** the attempt is recorded as failed with its error code

### Requirement: Warmup can be triggered on demand for one account

`POST /api/accounts/{account_id}/limit-warmup/trigger` SHALL send a warmup for the named
account immediately and return the outcome of that attempt.

The endpoint SHALL require the same dashboard session as the rest of the accounts router.
It SHALL reject an account that is not eligible for warmup — wrong provider, no
five-hour window on record, or a status that can never serve again — with a client error
naming the reason, rather than silently doing nothing.

The endpoint SHALL be usable while scheduled warmup is disabled, so an operator can open
a window by hand without turning on automatic warmup.

#### Scenario: An operator opens a window on demand

- **WHEN** an authenticated operator triggers warmup for an eligible Anthropic account
- **THEN** a warmup request is sent and the response reports whether it succeeded

#### Scenario: A paused account can be warmed on demand

- **WHEN** an operator triggers warmup for a paused Anthropic account that has a
  five-hour window on record
- **THEN** the warmup is sent
- **AND** the account remains paused

#### Scenario: Triggering works with scheduled warmup off

- **WHEN** the global warmup setting is disabled and an operator triggers warmup for an
  eligible account
- **THEN** the warmup is still sent

#### Scenario: An ineligible account is refused

- **WHEN** warmup is triggered for an account that reports no five-hour window
- **THEN** the request fails with a client error naming that reason

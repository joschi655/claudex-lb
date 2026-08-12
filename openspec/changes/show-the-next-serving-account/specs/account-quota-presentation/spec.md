## MODIFIED Requirements

### Requirement: The account list identifies the account that is serving

The account list SHALL identify the account that will carry the **next** request
of each provider, not the account that carried the last one. The distinction
SHALL be read from the pool's own next-serving answer rather than derived from
request activity or from routing policy: a request log can only report where
traffic went, which stops being the answer the moment an account is pinned,
paused, rate limited, or crosses a pace gate.

The indicator SHALL replace that account's status badge, since being next
already implies the account is able to serve.

It SHALL be scoped per provider: each provider names at most one account, so a
busier provider cannot speak for a quieter one.

When the pool reports its answer as uncertain, the list SHALL present it as the
likely next account rather than a definite one, so an operator is not told a
random draw is settled.

An account named as next while the pool is idle SHALL still be marked: "next" is
a statement about where traffic would go, and it is answerable with no traffic
at all. When the pool names no account — every account gated, or none
configured — no account SHALL be marked.

The list SHALL NOT promote a runner-up when the named account is hidden by a
search or status filter.

#### Scenario: The account the pool names is marked

- **GIVEN** the pool reports one account as next for a provider
- **WHEN** the account list renders
- **THEN** that account is marked as next
- **AND** the others show their status

#### Scenario: Each provider names its own

- **GIVEN** the pool names one Claude account and one Codex account
- **WHEN** the account list renders
- **THEN** both are marked

#### Scenario: An idle pool still names its next account

- **GIVEN** no account has served recently
- **AND** the pool names an account as next
- **WHEN** the account list renders
- **THEN** that account is marked as next

#### Scenario: A pool with no eligible account marks nobody

- **GIVEN** the pool names no account for any provider
- **WHEN** the account list renders
- **THEN** no account is marked
- **AND** every account shows its status

#### Scenario: An uncertain answer is presented as likely

- **GIVEN** the pool reports its answer as uncertain
- **WHEN** the account list renders
- **THEN** the marked account is presented as the likely next one

#### Scenario: Filtering does not promote a runner-up

- **GIVEN** the account named as next is hidden by a search or status filter
- **WHEN** the account list renders
- **THEN** no other account is marked in its place

## ADDED Requirements

### Requirement: The pin is a control of its own in the dashboard

The dashboard account view SHALL expose the pin as a control separate from the
routing policy selector, and the routing policy selector SHALL NOT offer the pin
as one of its values. The two SHALL be settable independently, so that pinning
an account does not require choosing a policy and choosing a policy does not
lift a pin.

The account list SHALL indicate the pin alongside the account's routing policy
rather than in place of it, so that a pinned `preserve` account reads as both.

#### Scenario: The policy selector does not offer the pin

- **WHEN** an operator opens the routing policy selector
- **THEN** its options are `normal`, `burn_first`, and `preserve`

#### Scenario: Pinning leaves the policy selector where it was

- **GIVEN** an account whose routing policy is `preserve`
- **WHEN** an operator pins it
- **THEN** the routing policy selector still reads `preserve`

#### Scenario: A pinned account shows both marks

- **GIVEN** a pinned account whose routing policy is `preserve`
- **WHEN** the account list renders
- **THEN** the account shows that it is pinned
- **AND** the account shows its `preserve` policy

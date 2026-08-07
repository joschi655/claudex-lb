## ADDED Requirements

### Requirement: Hard account pin

Routing policy `pinned` SHALL act as a hard selection override rather than a ranking
tier. While an account is pinned and able to serve, it SHALL be the only candidate the
selector considers.

"Able to serve" SHALL mean the account survives the same hard eligibility filters every
other account must survive: account status, quota and rate-limit state, cooldown, error
backoff, model plan eligibility, additional-quota eligibility, and any caller-supplied
account scope. A pinned account MUST NOT be excluded by the usage pace gates, by health
tier ranking, by routing-policy tier ranking, by the budget-safe preference path, or by
a session-stickiness mapping that names a different account.

When the pinned account is not able to serve, selection SHALL proceed over the remaining
accounts under the unchanged automatic rules. The pin SHALL NOT be cleared by that
release: it resumes as soon as the account is able to serve again. Only an explicit
routing-policy write clears it.

At most one account per provider SHALL hold policy `pinned`. Writing `pinned` to an
account SHALL clear `pinned` from every other account of the same provider in the same
operation, leaving accounts of other providers untouched.

#### Scenario: Pinned account serves ahead of a better candidate

- **GIVEN** a pinned account and a `normal` account
- **AND** the `normal` account has lower usage and would otherwise be selected
- **WHEN** the load balancer selects an account
- **THEN** it selects the pinned account

#### Scenario: Pace gates do not exclude a pinned account

- **GIVEN** a pinned account whose recorded usage is above its configured pace margin
- **AND** at least one other account is eligible
- **WHEN** the load balancer selects an account
- **THEN** it selects the pinned account
- **AND** the pinned account is not reported as pace-gated

#### Scenario: Health tier does not route around a pinned account

- **GIVEN** a pinned account in the `draining` health tier
- **AND** a `normal` account in the `healthy` health tier
- **WHEN** the load balancer selects an account
- **THEN** it selects the pinned account

#### Scenario: Exhausted pin releases to the automatic rules

- **GIVEN** a pinned account whose status is `quota_exceeded` with a future reset
- **AND** at least one other account is able to serve
- **WHEN** the load balancer selects an account
- **THEN** it selects one of the other accounts under the automatic rules
- **AND** the pinned account keeps routing policy `pinned`

#### Scenario: Pin resumes once the account recovers

- **GIVEN** a pinned account that released selection while rate limited
- **WHEN** its reset time passes and it becomes able to serve
- **THEN** the next selection returns to the pinned account without an operator action

#### Scenario: Pin does not bypass model eligibility

- **GIVEN** a pinned account that is not eligible for the requested model
- **WHEN** the load balancer selects an account for that model
- **THEN** the pinned account is excluded
- **AND** selection proceeds over the eligible accounts

#### Scenario: Pin outranks a session-stickiness mapping

- **GIVEN** a sticky session mapped to an account that is not the pinned account
- **AND** the pinned account is able to serve
- **WHEN** the load balancer selects an account for a request in that session
- **THEN** it selects the pinned account

#### Scenario: Pinning is exclusive within a provider

- **GIVEN** two accounts of the same provider, one of them pinned
- **WHEN** an operator pins the other one
- **THEN** the newly pinned account holds policy `pinned`
- **AND** the previously pinned account no longer holds policy `pinned`
- **AND** a pinned account of a different provider is unchanged

## MODIFIED Requirements

### Requirement: Manual account routing policy

Each account SHALL have a persisted manual routing policy with one of `normal`,
`burn_first`, `preserve`, or `pinned`. Missing or legacy values SHALL be treated as
`normal`.

`normal`, `burn_first`, and `preserve` SHALL rank accounts that have already passed
every hard eligibility filter. `pinned` SHALL instead override selection as specified in
"Hard account pin".

#### Scenario: expendable accounts are selected before normal accounts

- **GIVEN** at least one eligible account has routing policy `burn_first`
- **AND** at least one eligible account has routing policy `normal`
- **AND** no account has routing policy `pinned`
- **WHEN** the load balancer selects an account
- **THEN** it selects from the `burn_first` pool before considering `normal` accounts

#### Scenario: preserved accounts are fallback only

- **GIVEN** at least one eligible account has routing policy `normal`
- **AND** at least one eligible account has routing policy `preserve`
- **AND** no account has routing policy `pinned`
- **WHEN** the load balancer selects an account
- **THEN** it selects from the `normal` pool before considering `preserve` accounts

#### Scenario: routing policy does not bypass eligibility gates

- **GIVEN** a request is filtered by model plan or additional quota eligibility
- **WHEN** an account has routing policy `burn_first` or `pinned`
- **THEN** that account is still excluded if it fails the model plan or additional quota gate

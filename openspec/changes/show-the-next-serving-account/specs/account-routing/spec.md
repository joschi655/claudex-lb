## ADDED Requirements

### Requirement: The account pin is its own flag

The pin SHALL be persisted as an account field of its own, separate from the
account's routing policy. Setting or clearing the pin SHALL NOT change the
account's routing policy, and changing the routing policy SHALL NOT set or clear
the pin.

An account therefore holds both at once: the pin decides whether the account is
the only candidate, and the routing policy decides how the account ranks when it
is one of several. When a pin is lifted, the account SHALL resume the routing
policy it already held — no policy is inferred, restored from history, or reset
to a default on unpin.

At most one account per provider SHALL hold the pin. Pinning an account SHALL
clear the pin from every other account of the same provider in the same
operation, leaving accounts of other providers untouched.

Pinning SHALL be reachable through a dedicated endpoint that takes the flag on
its own. The response SHALL include the account's routing policy, so a caller
that has just unpinned can see which policy the account fell back to without a
second read.

Accounts persisted before this field existed SHALL keep their pin: a stored
routing policy of `pinned` SHALL be migrated to the flag. Because the earlier
implementation overwrote the policy when it pinned, the policy such an account
had before it was pinned is not recoverable, and the account SHALL be migrated
to `normal`.

#### Scenario: Unpinning restores the policy the account already had

- **GIVEN** an account with routing policy `preserve`
- **WHEN** an operator pins it and then unpins it
- **THEN** the account's routing policy is still `preserve`
- **AND** the account is no longer pinned

#### Scenario: Pinning does not disturb the policy

- **GIVEN** an account with routing policy `burn_first`
- **WHEN** an operator pins it
- **THEN** the account is pinned
- **AND** its routing policy is still `burn_first`

#### Scenario: Changing the policy does not disturb the pin

- **GIVEN** a pinned account
- **WHEN** an operator changes its routing policy
- **THEN** the account is still pinned

#### Scenario: The pin is exclusive within a provider

- **GIVEN** two accounts of the same provider, one of them pinned
- **WHEN** an operator pins the other one
- **THEN** only the newly pinned account is pinned
- **AND** a pinned account of a different provider is unchanged

#### Scenario: An existing pin survives the migration

- **GIVEN** a stored account whose routing policy is `pinned`
- **WHEN** the schema migration runs
- **THEN** the account is pinned
- **AND** its routing policy is `normal`

### Requirement: The pool reports which account would serve next

The pool SHALL answer, per provider, which account a new request would be
routed to, without routing one. Producing the answer SHALL take no lease, write
no session-stickiness mapping, record no usage, and persist nothing: asking must
not change the answer.

The answer SHALL be produced by the same selection logic that serves traffic,
under the same configured strategy, the same eligibility filters, and the same
budget thresholds and routing costs, so that an account excluded from selection
is excluded from the answer. In particular a paused, rate-limited, gated, or
otherwise ineligible account SHALL NOT be named, and a pinned account that is
able to serve SHALL be named.

A strategy that names one account outright SHALL still be subject to those
filters: the configured account SHALL be reported only if it is able to serve.

Concurrency caps SHALL NOT be applied, because the cap that governs a request
depends on the lease kind of a request that has not arrived.

The answer SHALL be scoped per provider, because each provider selects from its
own pool, and SHALL be read from the running proxy for that provider, so that
runtime state the database does not hold — leases, cooldowns, health tiers — is
reflected.

The answer SHALL declare its own certainty. When the configured strategy selects
at random among weighted candidates, the answer SHALL be reported as uncertain:
the named account is the most likely next hop, not a guarantee. When the
strategy is deterministic, when a pin decides the outcome, or when only one
candidate was available to draw from, the answer SHALL be reported as certain.

Certainty SHALL be read from the account that was selected, not from the pool
that was offered. A pin decides the outcome only when the pinned account
survived eligibility; a pinned account that cannot currently serve leaves the
pool ranking normally and SHALL NOT suppress the uncertainty flag.

When no account would be selected, the response SHALL name no account and SHALL
carry the reason.

A failure to preview one provider SHALL NOT fail the others.

#### Scenario: The account the selector would pick is the one reported

- **GIVEN** several eligible accounts of one provider
- **WHEN** the next-serving account is requested
- **THEN** the account named is the one the selector would return

#### Scenario: A pinned account is reported as next

- **GIVEN** a pinned account that is able to serve
- **AND** another account with more remaining quota
- **WHEN** the next-serving account is requested
- **THEN** the pinned account is named
- **AND** the answer is reported as certain

#### Scenario: An ineligible account is never reported

- **GIVEN** a paused account and an eligible account
- **WHEN** the next-serving account is requested
- **THEN** the eligible account is named

#### Scenario: A preview leaves no trace

- **GIVEN** a pool with sticky sessions and leases
- **WHEN** the next-serving account is requested
- **THEN** no lease is taken
- **AND** no session mapping is written
- **AND** a subsequent real request selects as though the preview had not run

#### Scenario: A randomized strategy is reported as uncertain

- **GIVEN** a routing strategy that draws at random among weighted candidates
- **AND** no account is pinned
- **WHEN** the next-serving account is requested
- **THEN** an account is named
- **AND** the answer is reported as uncertain

#### Scenario: A pin that cannot serve does not make the answer certain

- **GIVEN** a pinned account that is rate limited
- **AND** two other accounts that can serve
- **AND** a routing strategy that draws at random among weighted candidates
- **WHEN** the next-serving account is requested
- **THEN** one of the other accounts is named
- **AND** the answer is reported as uncertain

#### Scenario: A single candidate is certain under any strategy

- **GIVEN** a provider with exactly one account able to serve
- **WHEN** the next-serving account is requested
- **THEN** that account is named
- **AND** the answer is reported as certain

#### Scenario: An empty pool names nobody

- **GIVEN** a provider with no eligible account
- **WHEN** the next-serving account is requested
- **THEN** no account is named for that provider
- **AND** a reason is reported

#### Scenario: One provider failing does not hide the other

- **GIVEN** two providers, one of which cannot produce a preview
- **WHEN** the next-serving account is requested
- **THEN** the other provider still reports its account

#### Scenario: A single-account strategy still checks eligibility

- **GIVEN** a routing strategy configured to use one named account
- **AND** that account is paused
- **WHEN** the next-serving account is requested
- **THEN** that account is not named

## MODIFIED Requirements

### Requirement: Manual account routing policy

Each account SHALL have a persisted manual routing policy with one of `normal`,
`burn_first`, or `preserve`. Missing or legacy values SHALL be treated as
`normal`.

The routing policy SHALL NOT carry the pin. `pinned` is not a routing policy
value, and a write of `pinned` to the routing policy SHALL be rejected rather
than stored, so that the two controls cannot be confused for one another. The
pin is set through its own endpoint, as specified in "The account pin is its own
flag".

#### Scenario: expendable accounts are selected before normal accounts

- **GIVEN** at least one eligible account has routing policy `burn_first`
- **AND** at least one eligible account has routing policy `normal`
- **AND** no account is pinned
- **WHEN** the load balancer selects an account
- **THEN** it selects from the `burn_first` pool before considering `normal` accounts

#### Scenario: preserved accounts are fallback only

- **GIVEN** at least one eligible account has routing policy `normal`
- **AND** at least one eligible account has routing policy `preserve`
- **AND** no account is pinned
- **WHEN** the load balancer selects an account
- **THEN** it selects from the `normal` pool before considering `preserve` accounts

#### Scenario: routing policy does not bypass eligibility gates

- **GIVEN** a request is filtered by model plan or additional quota eligibility
- **WHEN** an account has routing policy `burn_first`
- **THEN** that account is still excluded if it fails the model plan or additional quota gate

#### Scenario: the pin is rejected as a routing policy

- **WHEN** a caller writes routing policy `pinned`
- **THEN** the write is rejected
- **AND** the account's routing policy is unchanged

### Requirement: Hard account pin

A pinned account SHALL act as a hard selection override rather than a ranking
tier. While an account is pinned and able to serve, it SHALL be the only
candidate the selector considers.

"Able to serve" SHALL mean the account survives the same hard eligibility filters every
other account must survive: account status, quota and rate-limit state, cooldown, error
backoff, model plan eligibility, additional-quota eligibility, and any caller-supplied
account scope. A pinned account MUST NOT be excluded by the usage pace gates, by health
tier ranking, by routing-policy tier ranking, by the budget-safe preference path, or by
a session-stickiness mapping that names a different account.

When the pinned account is not able to serve, selection SHALL proceed over the remaining
accounts under the unchanged automatic rules. The pin SHALL NOT be cleared by that
release: it resumes as soon as the account is able to serve again. Only an explicit
write to the pin clears it.

#### Scenario: Pinned account serves ahead of a better candidate

- **GIVEN** a pinned account and an unpinned account
- **AND** the unpinned account has lower usage and would otherwise be selected
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
- **AND** an unpinned account in the `healthy` health tier
- **WHEN** the load balancer selects an account
- **THEN** it selects the pinned account

#### Scenario: Exhausted pin releases to the automatic rules

- **GIVEN** a pinned account whose status is `quota_exceeded` with a future reset
- **AND** at least one other account is able to serve
- **WHEN** the load balancer selects an account
- **THEN** it selects one of the other accounts under the automatic rules
- **AND** the pinned account is still pinned

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

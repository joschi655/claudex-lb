## ADDED Requirements

### Requirement: Per-account usage ceilings

An account MAY carry an optional usage ceiling for the primary (5h) window,
`usage_ceiling_primary_pct`, and for the secondary (weekly) window,
`usage_ceiling_secondary_pct`. When a ceiling is set, the account MUST be excluded from
the selection pool while that window's recorded usage is greater than or equal to the
ceiling.

#### Scenario: Account below its ceiling is selectable

- **GIVEN** an account with `usage_ceiling_secondary_pct` of `80`
- **AND** recorded weekly usage of `79.9%`
- **THEN** the account remains in the selection pool

#### Scenario: Account at its ceiling is excluded

- **GIVEN** an account with `usage_ceiling_primary_pct` of `80`
- **AND** recorded 5h usage of `80%`
- **THEN** the account is excluded from the selection pool

### Requirement: Usage ceilings do not apply without a current sample

A ceiling MUST NOT exclude an account when that window's usage is unknown, or when the
window's reset timestamp is at or before the current time.

#### Scenario: A sample from an elapsed window does not hold the account

- **GIVEN** an account with `usage_ceiling_primary_pct` of `80`
- **AND** its last recorded 5h usage is `85%`
- **AND** that window's reset timestamp has already passed
- **THEN** the ceiling does not exclude the account

#### Scenario: Unknown usage does not hold the account

- **GIVEN** an account with `usage_ceiling_primary_pct` of `50` and no recorded 5h usage
- **THEN** the ceiling does not exclude the account

### Requirement: Usage ceiling range

Ceilings MUST be accepted only in the range greater than `0` and at most `100`, on the
account API and in per-key routing rules.

#### Scenario: Ceiling outside the accepted range is rejected

- **WHEN** an operator submits a ceiling of `0`, a negative value, or a value above `100`
- **THEN** the request is rejected with a validation error
- **AND** the stored configuration is unchanged

### Requirement: Usage ceilings are hard filters

An account excluded by a usage ceiling MUST NOT be reachable through any later selection
tier, including `burn_first`, budget-safe fallback, backoff fallback, and session
stickiness.

#### Scenario: Burn-first does not lift a ceiling

- **GIVEN** a `burn_first` account at its weekly ceiling
- **AND** another eligible account
- **THEN** the other account is selected

### Requirement: A pin does not lift a usage ceiling

The operator pin MUST NOT exempt an account from its usage ceilings, while it continues to
exempt the account from its pace gates.

#### Scenario: A pinned account at its ceiling falls through

- **GIVEN** a pinned account with `usage_ceiling_primary_pct` of `80` and 5h usage of `90%`
- **AND** another eligible account
- **THEN** the other account is selected

#### Scenario: A pin still lifts pace gates below the ceiling

- **GIVEN** a pinned account with `usage_ceiling_primary_pct` of `90` and 5h usage of `70%`
- **AND** a primary pace margin that the account currently fails
- **THEN** the pinned account is selected

### Requirement: Whole pool at its usage ceilings

When every candidate is excluded by usage ceilings, selection MUST fail with an error that
names usage ceilings as the cause.

#### Scenario: Every account held

- **GIVEN** every candidate account has reached a configured ceiling
- **WHEN** an account is requested
- **THEN** selection returns no account
- **AND** the error message identifies usage ceilings as the reason

### Requirement: Per-API-key account routing rules are key-scoped

An API key MAY carry at most one routing rule per account. A rule MUST change only how
that account is ranked and gated for requests authenticated with that key. It MUST NOT
change which accounts the key may reach, and it MUST NOT change selection for any other
key or for unauthenticated traffic.

#### Scenario: Two keys draw the same pool differently

- **GIVEN** account A with `usage_ceiling_secondary_pct` of `80` and weekly usage of `85%`
- **AND** account B with weekly usage of `20%`
- **AND** key K1 without rules
- **AND** key K2 with a rule for A of `routing_policy` `burn_first` and `override_gates` true
- **WHEN** a request authenticates with K1
- **THEN** account B is selected
- **WHEN** a request authenticates with K2
- **THEN** account A is selected

### Requirement: Routing rule policy override

A rule's `routing_policy`, when set, MUST replace the account's routing policy for that
key. When unset, the account's own policy MUST apply.

#### Scenario: Policy override keeps the account's gates

- **GIVEN** account A with `usage_ceiling_primary_pct` of `80`
- **AND** key K with a rule for A of `routing_policy` `burn_first` and `override_gates` false
- **WHEN** account A reaches `80%` of its 5h window
- **THEN** account A is excluded for requests authenticated with K

### Requirement: Routing rule gate override

A rule with `override_gates` true MUST replace all five of the account's gates
(`usage_ceiling_primary_pct`, `usage_ceiling_secondary_pct`, `pace_margin_primary_pct`,
`pace_margin_secondary_pct`, `pre_reset_window_minutes`) with the rule's values, where an
unset value switches that gate off for the key. A rule with `override_gates` false MUST
leave the account's gates in force.

#### Scenario: Unset value switches a gate off for the key

- **GIVEN** account A with `usage_ceiling_primary_pct` of `80`
- **AND** key K with a rule for A of `override_gates` true and no ceilings
- **WHEN** account A reaches `85%` of its 5h window
- **THEN** account A remains selectable for requests authenticated with K

### Requirement: Inheriting rules are not stored

A rule that sets neither a policy nor `override_gates` MUST be treated as absent and MUST
NOT be stored.

#### Scenario: An all-inherit rule is dropped

- **WHEN** an operator saves a rule for an account with no policy and `override_gates` false
- **THEN** the key's returned `accountRoutingRules` does not contain that account

### Requirement: Routing rules on the API-key API

The dashboard API-key API MUST return each key's stored rules as `accountRoutingRules`
and MUST accept `PUT /api/api-keys/{key_id}/account-routing-rules` with a full list of
rules that replaces the key's stored rules.

#### Scenario: Rules round trip

- **WHEN** an operator replaces a key's rules
- **THEN** the response and later key listings return exactly the stored rules

### Requirement: Routing rule validation

A rules update MUST be rejected with a validation error, leaving the stored rules
unchanged, when it names an unknown account, names an account more than once, carries an
unknown routing policy, or carries a gate value outside the account API's ranges.

#### Scenario: Unknown account is rejected

- **WHEN** an operator submits a rule for an account id that does not exist
- **THEN** the request is rejected with a validation error
- **AND** the key's stored rules are unchanged

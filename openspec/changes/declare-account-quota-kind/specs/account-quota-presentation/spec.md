## ADDED Requirements

### Requirement: An account declares which quota surface it presents

Each account SHALL carry a persisted quota kind with one of `auto`,
`subscription`, or `usage_based`. Missing or unrecognized values SHALL be
treated as `auto`.

`auto` SHALL resolve the kind from the account's own usage data, presenting a
budget surface when the account reports a dollar budget and no rolling window,
and window surfaces otherwise. This is the default for every account, including
accounts that existed before the setting, so an installation that never sets it
behaves exactly as it did before.

An explicitly set kind SHALL win over that inference. A `usage_based` account
SHALL present its budget and credits and SHALL NOT present rolling-window bars.
A `subscription` account SHALL present its rolling windows and SHALL NOT present
a budget bar in their place.

An explicitly set kind whose data is absent SHALL present that kind's surface in
an empty state, and SHALL NOT fall back to the other kind's surface. A setting
that silently reverts to what the operator overrode is worse than no setting,
because the operator cannot tell that it did.

Setting the quota kind SHALL NOT change the account's routing policy, pin, or
pace gates, and SHALL NOT change which account the pool selects. It governs
presentation only.

The quota kind SHALL be readable on the account summary and settable through a
dedicated endpoint, and SHALL be offered as a per-account control in the
dashboard.

#### Scenario: A usage-based account presents its budget

- **GIVEN** an account whose quota kind is `usage_based`
- **AND** it reports a dollar budget
- **WHEN** the accounts view renders it
- **THEN** its budget is shown
- **AND** no rolling-window bars are shown

#### Scenario: An explicit kind wins over the data

- **GIVEN** an account that reports rolling windows
- **WHEN** its quota kind is set to `usage_based`
- **THEN** the accounts view stops showing its rolling-window bars

#### Scenario: A subscription account keeps its windows even with a budget

- **GIVEN** an account that reports both a dollar budget and rolling windows
- **WHEN** its quota kind is set to `subscription`
- **THEN** the accounts view shows its rolling-window bars

#### Scenario: An explicit kind with no data does not fall back

- **GIVEN** an account whose quota kind is `usage_based`
- **AND** it reports no dollar budget
- **WHEN** the accounts view renders it
- **THEN** it presents an empty budget surface
- **AND** no rolling-window bars are shown

#### Scenario: The default is unchanged behaviour

- **GIVEN** an account whose quota kind has never been set
- **WHEN** the accounts view renders it
- **THEN** it presents whichever surface its usage data implies

#### Scenario: The kind does not disturb routing

- **GIVEN** an account with a routing policy and a pin
- **WHEN** its quota kind is changed
- **THEN** its routing policy and pin are unchanged

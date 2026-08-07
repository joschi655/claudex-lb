# account-quota-presentation Specification Delta

## ADDED Requirements

### Requirement: Accounts present their extra-usage pool

An account that reports an extra-usage pool SHALL present it alongside whatever quota
surface it already has, rather than in place of it: the pool is the headroom behind the
plan's limits, not the plan's own quota, and an account can report both at once.

When the pool is enabled the presentation SHALL show its utilization and the amount spent
against the amount available. When the pool is disabled the presentation SHALL say so
explicitly rather than omitting the pool, because a switched-off pool is the state an
operator acts on.

An account that reports no pool at all SHALL render exactly as before, with no
extra-usage surface.

#### Scenario: An enabled pool shows its spend

- **GIVEN** an account reporting an enabled extra-usage pool with a limit and spend
- **WHEN** the account's usage panel renders
- **THEN** it shows the pool's utilization and the spent and remaining amounts, in
  addition to the account's own window or budget surface

#### Scenario: A disabled pool is shown as off

- **GIVEN** an account reporting an extra-usage pool that is not enabled
- **WHEN** the account's usage panel renders
- **THEN** the pool is shown with an explicit off state rather than omitted

#### Scenario: An account with no pool is unchanged

- **WHEN** an account reports no extra-usage pool
- **THEN** its usage panel renders with no extra-usage surface

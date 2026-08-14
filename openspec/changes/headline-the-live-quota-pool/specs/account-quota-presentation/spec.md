# account-quota-presentation Specification Delta

## ADDED Requirements

### Requirement: A usage-based account presents the pool it can still spend from

An account resolved as usage-based bills against a plan budget and, behind it, an
extra-usage pool. Compact quota surfaces — the account list row, the dashboard
account card, and the dashboard account list — SHALL present the account's **live
pool**: the first of those two, in that order, that still has headroom. A pool has
headroom when its utilization is below 100%.

The extra-usage pool SHALL be considered only when it is enabled. A disabled pool
is not a pool the account can spend from, so it MUST NOT be selected as live even
when the plan budget is exhausted.

The presented pool SHALL be labelled by which pool it is, so an operator can tell
a plan budget from the extra-usage pool without opening the account.

#### Scenario: A spent plan budget hands off to the extra-usage pool

- **GIVEN** a usage-based account whose plan budget is 100% used
- **AND** an enabled extra-usage pool that is 42% used with an amount remaining
- **WHEN** a compact quota surface renders the account
- **THEN** it presents the extra-usage pool, showing the pool's remaining
  percentage and remaining amount
- **AND** it identifies the presented pool as the extra-usage pool

#### Scenario: A plan budget with headroom is the live pool

- **GIVEN** a usage-based account whose plan budget is 40% used
- **AND** an enabled extra-usage pool
- **WHEN** a compact quota surface renders the account
- **THEN** it presents the plan budget rather than the extra-usage pool

#### Scenario: A disabled extra-usage pool is never selected

- **GIVEN** a usage-based account whose plan budget is 100% used
- **AND** an extra-usage pool that is not enabled
- **WHEN** a compact quota surface renders the account
- **THEN** it presents the spent plan budget rather than the disabled pool

### Requirement: A usage-based account with every pool spent presents as spent

When neither the plan budget nor the extra-usage pool has headroom, compact quota
surfaces SHALL present the account as spent rather than selecting a pool
arbitrarily, and MUST NOT fall back to window bars for an account resolved as
usage-based.

A usage-based account that has reported no pool at all SHALL state that no budget
has been read yet, which is the existing behaviour for that case.

#### Scenario: Both pools spent

- **GIVEN** a usage-based account whose plan budget and enabled extra-usage pool
  are both 100% used
- **WHEN** a compact quota surface renders the account
- **THEN** it presents the account as having nothing left to spend
- **AND** it does not render 5h, weekly, or monthly bars for that account

### Requirement: Dashboard quota surfaces honour the resolved quota kind

The dashboard page's account card and account list SHALL resolve an account's
quota kind by the same rule the accounts page uses, and MUST NOT render 5h,
weekly, or monthly bars for an account resolved as usage-based.

#### Scenario: Dashboard card shows a usage-based seat's pool

- **GIVEN** a usage-based account reporting no rolling window and a dollar pool
- **WHEN** the dashboard account card renders
- **THEN** the card shows the account's live pool with its remaining amount
- **AND** the card renders no 5h or weekly bar

#### Scenario: Dashboard list row shows a usage-based seat's pool

- **GIVEN** a usage-based account reporting no rolling window and a dollar pool
- **WHEN** the dashboard account list renders the account's quota cell
- **THEN** the cell shows the account's live pool
- **AND** the cell renders no 5h or weekly entry

### Requirement: A subscription account is unaffected

An account resolved as subscription SHALL present its windows exactly as before,
whether or not it also reports a dollar pool.

#### Scenario: Subscription account keeps its window bars

- **GIVEN** an account resolved as subscription that reports a five-hour and a
  weekly window
- **WHEN** any quota surface renders the account
- **THEN** it presents those windows, unchanged by the presence or absence of a
  dollar pool

# account-quota-presentation Specification Delta

## ADDED Requirements

### Requirement: Budget-quota accounts present their budget in place of windows

An account whose quota is a dollar budget rather than a rolling window SHALL present that
budget wherever a window-based account presents its five-hour and weekly bars: the
account row SHALL show the budget's utilization, the amount spent against the amount
available, and the date the budget resets. Such an account SHALL NOT be presented as
having no quota information merely because it reports no five-hour window.

Window-based accounts SHALL be unaffected — the budget surface appears only for accounts
that actually report a budget.

#### Scenario: A budget account shows a spend bar

- **GIVEN** an account with a `budget` usage row and dollar figures on its summary
- **WHEN** the accounts view renders it
- **THEN** the row shows the budget utilization, the spent and available amounts, and the
  reset date

#### Scenario: A window account shows no spend bar

- **WHEN** an account reports five-hour and weekly windows and no budget
- **THEN** its row renders exactly as before, with no spend surface

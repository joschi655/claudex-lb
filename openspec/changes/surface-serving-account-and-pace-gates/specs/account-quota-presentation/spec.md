## ADDED Requirements

### Requirement: The account list identifies the account that is serving

The account list SHALL distinguish the account currently carrying traffic from
the accounts that are merely eligible. The distinction SHALL be derived from
recent request activity, not from routing policy — a pinned or `burn_first`
account can be marked and still be serving nothing, and the list MUST show what
is happening rather than what was requested.

The serving indicator SHALL replace that account's status badge, since serving
already implies the account is able to serve.

Serving SHALL be scoped per provider: each provider names at most one serving
account, so a busier provider cannot speak for a quieter one.

#### Scenario: The newest request marks its account

- **GIVEN** several accounts of one provider with recent requests
- **WHEN** the account list renders
- **THEN** the account with the newest request shows as serving
- **AND** the others show their status

#### Scenario: Each provider names its own

- **GIVEN** one Claude account and one Codex account, both with recent requests
- **WHEN** the account list renders
- **THEN** both show as serving

#### Scenario: An idle pool names nobody

- **GIVEN** no account has served recently
- **WHEN** the account list renders
- **THEN** no account shows as serving
- **AND** every account shows its status

#### Scenario: Filtering does not promote a runner-up

- **GIVEN** the serving account is hidden by a search or status filter
- **WHEN** the account list renders
- **THEN** no other account is shown as serving in its place

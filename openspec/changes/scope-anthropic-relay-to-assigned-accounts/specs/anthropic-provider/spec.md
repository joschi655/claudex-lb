# anthropic-provider Delta

## ADDED Requirements

### Requirement: The relay honours an API key's account assignments

When the API key authenticating a relayed request has
`account_assignment_scope_enabled` set, account selection MUST be restricted to that
key's assigned account ids. Failover MUST continue to operate within the restricted
set. When every assigned account is unavailable, the relay MUST return its usual
no-account-available response and MUST NOT widen selection back to the full pool.

Selection MUST remain unrestricted when the key has scoping disabled, when its
assignment set is empty, and when the request carries no API key because proxy
authentication is disabled.

#### Scenario: A scoped key reaches only its assigned account

- **GIVEN** two anthropic accounts and an API key scoped to the second
- **WHEN** a request authenticated by that key is relayed
- **THEN** the balancer is asked only for the assigned account id and the request is
  served by the second account

#### Scenario: Failover happens inside the scope

- **GIVEN** three anthropic accounts and an API key scoped to two of them
- **WHEN** the first assigned account returns `429` and the second returns `200`
- **THEN** the caller receives the `200`, and the account outside the scope is never
  attempted

#### Scenario: An exhausted scope does not widen

- **GIVEN** an API key scoped to one anthropic account that is unavailable
- **WHEN** a request authenticated by that key is relayed
- **THEN** the caller receives the no-account-available response and no unassigned
  account is attempted

#### Scenario: An unscoped key is unaffected

- **GIVEN** an API key with `account_assignment_scope_enabled` unset but assignments
  present
- **WHEN** a request authenticated by that key is relayed
- **THEN** account selection is not restricted

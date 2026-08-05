# anthropic-provider Delta

## ADDED Requirements

### Requirement: Spent subscription usage fails over instead of reaching the caller

A `400` response whose body names spent subscription usage MUST be treated as an
exhausted account rather than an invalid request. The relay MUST mark the serving
account rate-limited, record the attempt as `rate_limit_exceeded`, and continue to
the next candidate account. When no candidate remains, the caller MUST receive the
last upstream body and status unchanged.

Classification MUST be driven by the response body, not by the status alone: a `400`
that does not name spent usage MUST keep the existing verbatim pass-through with no
account-health write and no failover.

#### Scenario: A drained account is skipped

- **GIVEN** two anthropic accounts
- **WHEN** the first returns `400` with body text `You're out of extra usage. Add
  more at claude.ai/settings/usage and keep going.` and the second returns `200`
- **THEN** the caller receives the second account's `200` response, the first
  account is marked rate-limited, and its attempt is logged with error code
  `rate_limit_exceeded`

#### Scenario: The whole pool is drained

- **GIVEN** every anthropic account returns the spent-usage `400`
- **WHEN** the relay exhausts its candidates
- **THEN** the caller receives `400` with the upstream body unchanged

#### Scenario: An ordinary client error is untouched

- **GIVEN** an anthropic account returning `400` with body text
  `{"type":"error","error":{"type":"invalid_request_error","message":"bad model"}}`
- **WHEN** the request is relayed
- **THEN** the caller receives that response verbatim, no second account is tried,
  and the attempt is logged with error code `invalid_request`

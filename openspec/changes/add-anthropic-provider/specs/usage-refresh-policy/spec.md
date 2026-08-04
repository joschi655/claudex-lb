# usage-refresh-policy Delta

## ADDED Requirements

### Requirement: OpenAI usage flows reject Anthropic accounts

Every service that calls an OpenAI or ChatGPT upstream endpoint per account
MUST enforce the OpenAI provider at its shared dispatch boundary. Batch flows
MUST skip Anthropic accounts, and direct account actions MUST reject them with a
provider-specific error. Anthropic credentials MUST never be sent to an OpenAI
endpoint, including when paused accounts are explicitly included.

#### Scenario: Batch refresh ignores Anthropic accounts

- **GIVEN** active OpenAI and Anthropic accounts
- **WHEN** any OpenAI usage, fleet, model, warmup, quota, or automation batch runs
- **THEN** only OpenAI credentials may reach its upstream dispatcher

#### Scenario: Direct OpenAI action rejects Claude

- **GIVEN** an Anthropic account id
- **WHEN** an operator invokes an OpenAI-only account action
- **THEN** the action fails before decrypting or dispatching the credential

### Requirement: Anthropic API-key rate limits are passive

Anthropic API-key accounts MUST NOT enter the OpenAI usage refresh machinery.
The Messages relay MAY persist standard Anthropic request and token rate-limit
headers, treating missing or malformed values as absent metadata rather than a
request failure.

#### Scenario: Relay records a standard reset

- **WHEN** Anthropic returns a request or token reset as an RFC 3339 timestamp
- **THEN** the persisted provider quota snapshot contains the corresponding UTC reset

# usage-refresh-policy Delta

## ADDED Requirements

### Requirement: OpenAI usage flows skip anthropic accounts

Schedulers and account actions that call OpenAI/ChatGPT upstream endpoints per account (usage refresh, rate-limit reset credits, model refresh, quota planning, probe, OpenAI-format auth export) MUST skip anthropic accounts or reject them with a clear error; they MUST NOT send anthropic credentials to OpenAI endpoints.

#### Scenario: Usage refresh ignores anthropic accounts

- **GIVEN** accounts of both providers
- **WHEN** the OpenAI usage refresh cycle runs
- **THEN** only openai accounts are polled

### Requirement: Proactive anthropic token freshness

When the auth guardian is enabled, an OAuth anthropic account whose access token expires within its staleness horizon MUST be refreshed proactively through the claim-serialized refresh path, keeping idle accounts sign-in-free.

#### Scenario: Idle account stays fresh

- **GIVEN** the guardian enabled and an anthropic account expiring within the horizon
- **WHEN** the guardian cycle runs
- **THEN** the account's token is refreshed and rotated material persisted

# account-routing Delta

## ADDED Requirements

### Requirement: Selection is provider-scoped

Account selection MUST be scoped to a single provider per request: a selection for one provider MUST never return another provider's account, selection caches MUST key on the provider, and existing call sites without an explicit provider keep OpenAI semantics unchanged.

#### Scenario: Providers never cross

- **GIVEN** active accounts of both providers
- **WHEN** an anthropic selection and an openai selection run
- **THEN** each returns only accounts of its own provider

#### Scenario: Default call sites unchanged

- **WHEN** an existing OpenAI proxy path selects an account without naming a provider
- **THEN** only `openai` accounts are considered, matching pre-change behavior

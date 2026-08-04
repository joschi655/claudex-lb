## 1. Contract and schema safety

- [x] 1.1 Replace consumer OAuth requirements with Console API-key onboarding, relay, analytics, and dashboard requirements
- [x] 1.2 Add typed provider/credential-kind fields and a forward migration that quarantines legacy Anthropic rows
- [x] 1.3 Make migrations upgrade/downgrade safe and add migration data tests
- [x] 1.4 Restore required Python typecheck after nullable token changes

## 2. Credential onboarding and provider boundaries

- [x] 2.1 Add create/replace Anthropic API-key dashboard APIs with encrypted storage, audit, no-store responses, and exact-row replacement
- [x] 2.2 Remove Claude.ai OAuth import/refresh behavior and reject non-OpenAI OAuth reauthentication targets
- [x] 2.3 Enforce provider guards at all OpenAI dispatch boundaries, including fleet, limits, warmups, quota planning, automations, and reset actions
- [x] 2.4 Add provider-boundary and credential onboarding regression coverage

## 3. Anthropic relay hardening

- [x] 3.1 Keep canonical Messages routes only and apply firewall/body/concurrency protections
- [x] 3.2 Enforce client API-key account/model scope, reservations, settlement, and last-used tracking
- [x] 3.3 Add provider request logging and Anthropic usage extraction for JSON and SSE responses
- [x] 3.4 Fix single-account routing, connect/pre-first-byte failover, mid-stream/disconnect cleanup, 401/403/429 classification, and RFC 3339 resets
- [x] 3.5 Add relay integration tests for security, accounting, logging, failover, and oversized bodies

## 4. Provider-aware dashboard

- [x] 4.1 Add `all|openai|anthropic` filters to account, overview, projection, and request-log APIs
- [x] 4.2 Add shared provider scope controls and provider-specific dashboard capacity presentation
- [x] 4.3 Add Claude API-key create/replace UI and hide all OpenAI-only account actions and polling
- [x] 4.4 Add frontend schema, hook, component, and integration coverage
- [x] 4.5 Add published Claude API-key setup documentation linked to the owning OpenSpec capability

## 5. Validation and rollout readiness

- [x] 5.1 Run focused backend/frontend suites, full pytest, ruff, ty, frontend typecheck/lint/tests, and migration graph checks
- [x] 5.2 Run strict OpenSpec validation when the CLI is available and reconcile all artifacts/tasks
- [ ] 5.3 Review the final diff against current-head Codex findings and document live quarantine/deployment verification steps

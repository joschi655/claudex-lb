# Tasks

## 1. Schema

- [x] 1.1 Nullable `usage_ceiling_primary_pct` / `usage_ceiling_secondary_pct` on `Account`
- [x] 1.2 Table `api_key_account_routing_rules` keyed by (api key, account), cascading on delete
- [x] 1.3 Alembic revision on the current single head; upgrade and downgrade

## 2. Selection

- [x] 2.1 `evaluate_usage_ceilings` and `evaluate_eligibility_gates` in `app/core/balancer/logic.py`
- [x] 2.2 Ceilings apply to pinned accounts; pace gates still do not
- [x] 2.3 Whole-pool-at-ceiling error names usage ceilings
- [x] 2.4 `AccountRoutingRule` + `apply_routing_rule` in `app/core/balancer/routing_rules.py`
- [x] 2.5 `_build_states` applies the calling key's rules to request-scoped states only
- [x] 2.6 Rules passed from every selection call site that knows the key (Codex HTTP/WebSocket/compact
      selection in `proxy/service.py`, control-account selection, Anthropic relay)

## 3. API

- [x] 3.1 Ceilings on the account read model and `PUT /api/accounts/{id}/pace-gates`
- [x] 3.2 `accountRoutingRules` on API-key responses; `PUT /api/api-keys/{id}/account-routing-rules`
- [x] 3.3 Validation: unknown account, duplicate account, unknown policy, ranges

## 4. Clients

- [x] 4.1 Dashboard: ceiling fields with presets, ceiling marker on usage bars, per-key routing editor
- [x] 4.2 Menu bar: `ceiling <id> <5h|7d> <pct|clear>`, presets, "at ceiling" marker
- [x] 4.3 Docs: `docs/usage-ceilings.md`, linked from pace gates, account pin and API keys pages

## 5. Tests

- [x] 5.1 Unit: inclusive boundary, unknown usage, elapsed window, burn-first, pin, whole pool
- [x] 5.2 Unit: rule application (policy only, gate override, none switches off)
- [x] 5.3 Integration: account API round trip and range validation
- [x] 5.4 Integration: API-key rules round trip, validation, and a proxied request per key
      landing on different accounts

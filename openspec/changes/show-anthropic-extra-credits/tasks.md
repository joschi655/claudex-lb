## 1. Ingest

- [x] 1.1 `EXTRA_CREDITS_WINDOW` constant; `persist_usage_api_snapshot` writes the pool
      (enabled or not), deriving the remainder from limit and spend
- [x] 1.2 `AnthropicUsageApiSnapshot.has_any` counts a pool-only snapshot as usage
- [x] 1.3 Poller unchanged-write fingerprint includes the pool's enabled state, spend and limit

## 2. API surface

- [x] 2.1 `AccountExtraCredits` schema + `extra_credits` on `AccountSummary`
- [x] 2.2 `_extra_credits` mapper, derived spend, `credits_has` → `enabled`
- [x] 2.3 Service reads the newest `extra_credits` row per account and threads it through

## 3. Dashboard

- [x] 3.1 `AccountExtraCreditsSchema` + `extraCredits` on the account summary schema
- [x] 3.2 `ExtraCreditsRow` in the account usage panel — spend bar when enabled, explicit
      off state when not

## 4. Tests

- [x] 4.1 Poller: enabled pool written with derived remainder; disabled pool still written
- [x] 4.2 `/api/accounts` integration: enabled, disabled, and absent pools
- [x] 4.3 Dashboard: renders alongside windows, renders off state, absent when unreported

## 5. Follow-up (not this change)

- [ ] 5.1 Enabling the pool from the dashboard —
      `PUT /api/oauth/organizations/{orgUUID}/overage_spend_limit` (+ one-time
      `setup_overage_billing`), behind an explicit confirmation. Authorizes real spend.

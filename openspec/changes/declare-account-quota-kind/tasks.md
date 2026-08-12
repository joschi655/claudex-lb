# Tasks

## 1. Storage

- [x] 1.1 `AccountQuotaKind` enum and `accounts.quota_kind`, defaulting to `auto`
- [x] 1.2 Migration `20260812_010000_add_account_quota_kind` — add the column
      with a server default of `auto`, which is what every existing row already
      behaved as
- [x] 1.3 `AccountsRepository.set_quota_kind` — write the kind and nothing else

## 2. API

- [x] 2.1 Normalize unknown and missing values to `auto` in the mapper, beside
      the routing-policy normalizer
- [x] 2.2 Carry `quota_kind` on the account summary
- [x] 2.3 `AccountsService.set_quota_kind`, invalidating the selection cache
- [x] 2.4 `PUT /api/accounts/{id}/quota-kind`

## 3. Presentation

- [x] 3.1 One resolver shared by both surfaces: explicit kind wins, `auto` falls
      back to the existing inference. Neither surface re-derives it
- [x] 3.2 Account list row and account usage panel read the resolved kind
- [x] 3.3 An explicit kind with no data renders that kind's empty state rather
      than the other kind's surface
- [x] 3.4 A control in `account-actions.tsx`, beside the routing policy

## 4. Tests

- [x] 4.1 `tests/integration/test_accounts_api_quota_kind.py` — the kind round
      trips, an unknown stored value reads as `auto`, an unknown written value
      is rejected, and setting it leaves the routing policy and pin alone
- [x] 4.2 `tests/integration/test_account_quota_kind_migration.py` — existing
      rows land on `auto` and a re-run does not reset a kind since set
- [x] 4.3 Frontend: the resolver's cases, both surfaces honouring it, and the
      empty state that does not fall back

## 5. Review fixes

- [x] 5.1 The resolver's `auto` branch first counted `resetAt` and
      `windowMinutes` as evidence of a live window, which is stricter than the
      inference it replaced and flipped a budget seat with stale window
      metadata back to the subscription presentation. Caught by the existing
      `account-usage-panel` test; the auto branch now reads the remaining
      percentages alone, and a regression test names the case

## 6. Verification

- [x] 6.1 `uv run pytest` and `bun run test` green
- [ ] 6.2 Deploy, then confirm against live: check24 set to `usage_based`
      presents its budget, and a subscription seat is unchanged

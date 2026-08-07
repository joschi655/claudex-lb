# Tasks

## 1. Backend

- [x] 1.1 `last_served_at_by_account(since, account_ids)` on `AccountsRepository`,
      bounded by time so it answers "now" without scanning the log
- [x] 1.2 Thread it through `build_account_summaries` and `_account_to_summary`
- [x] 1.3 Report it as `last_served_at` on `AccountSummary`
- [x] 1.4 Call it from `list_accounts` with the recent window

## 2. Frontend — serving

- [x] 2.1 `servingAccountIds()` — newest request per provider, from the summary
- [x] 2.2 Compute over the full account set, not the filtered view
- [x] 2.3 Render a `Serving` badge in place of the status badge

## 3. Frontend — pace gates

- [x] 3.1 Carry the three gates on the account summary schema
- [x] 3.2 `updateAccountPaceGates` client + request/response schemas
- [x] 3.3 `paceGatesMutation` in `use-accounts`
- [x] 3.4 `PaceGateFields` — one input per gate, empty means off
- [x] 3.5 Thread the handler through detail and page
- [ ] 3.6 Before/after screenshots on the PR

## 4. Tests

- [x] 4.1 Unit: newest request per account; window excludes older activity;
      account scope, including the empty scope; rows with no account ignored
- [x] 4.2 Unit: serving is per provider; idle pool names nobody; unparseable
      timestamp does not win; empty pool
- [x] 4.3 API: gates round-trip through the listing, untouched gates stay unset
- [x] 4.4 API: an idle account reports no serving time

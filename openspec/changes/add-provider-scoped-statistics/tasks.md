# Tasks

## 1. Schema

- [x] 1.1 Add `provider` to the `RequestLog` model (nullable string, indexed)
- [x] 1.2 Alembic revision on top of `20260804_000000_add_account_pace_gates`: add the
      column, backfill from `accounts.provider` where the account still exists, default
      the rest to `openai`
- [x] 1.3 Downgrade drops the index and the column

## 2. Write path

- [x] 2.1 Resolve the serving account's provider alongside `plan_type` in
      `RequestLogsRepository.add_log`, in one lookup rather than two
- [x] 2.2 Accept an explicit `provider` argument so a caller that already knows it does not
      pay for the lookup

## 3. Read path

- [x] 3.1 `providers` filter in `_build_filters`
- [x] 3.2 Thread it through `list_recent`, the service layer, and the API query parameter
- [x] 3.3 Include `provider` in the request-log entry mapper and schema
- [x] 3.4 Report distinct providers from the filter-options endpoint
- [x] 3.5 Same filter on the reports repository/service/API, applied to every aggregate

## 4. Frontend

- [x] 4.1 Provider filter control on the request-log filter bar, sourced from the options
      endpoint, hidden when only one provider has traffic
- [x] 4.2 Provider visible on the request-log row
- [x] 4.3 Provider filter on the reports filter bar
- [x] 4.4 Types and mock handlers updated

## 5. Tests

- [x] 5.1 Repository: filtering by provider returns only that provider's rows; no filter
      returns all
- [x] 5.2 Repository: a row keeps its provider after its account is deleted
- [x] 5.3 API: `provider` query parameter and the entry field
- [x] 5.4 Options: distinct providers reported
- [x] 5.5 Reports: aggregates respect the provider filter
- [x] 5.6 Migration: backfill sets `anthropic` from the account and `openai` for orphans
- [x] 5.7 Frontend: filter renders, drives the query, and stays hidden for one provider

## 6. Docs

- [x] 6.1 Extend the Claude statistics page with how to read one provider at a time

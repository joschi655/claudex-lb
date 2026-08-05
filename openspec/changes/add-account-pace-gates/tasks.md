# Tasks

## 1. Schema

- [x] 1.1 Add nullable `pace_margin_primary_pct` (float), `pace_margin_secondary_pct`
      (float), `pre_reset_window_minutes` (int) to `Account` in `app/db/models.py`
- [x] 1.2 Alembic revision on the current single head; upgrade + downgrade both
      implemented. Existing rows keep NULL, which is the documented "gate off" value,
      so no backfill is required.

## 2. Selection

- [x] 2.1 Carry the three fields onto `AccountState` in `app/core/balancer/logic.py`
- [x] 2.2 Add `secondary_window_minutes` to `AccountState`, defaulting to the 7-day
      weekly window, so the secondary pace line has a defined length
- [x] 2.3 Implement `evaluate_pace_gates(state, now)` returning the failing gate name
      or `None`; not-evaluable gates return `None` per spec
- [x] 2.4 Apply it in the `select_account` availability loop so gated accounts are
      dropped before any ranking tier sees them
- [x] 2.5 Report an all-gated pool with a pace-gate-specific error message
- [x] 2.6 Populate the fields in `_build_account_state` in
      `app/modules/proxy/load_balancer.py`

## 3. API

- [x] 3.1 Add the three nullable fields to the account read + update schemas with
      `0`–`100` validation on the margins and `>= 0` on the minutes
- [x] 3.2 Map them in `app/modules/accounts/mappers.py`
- [x] 3.3 Honor "omitted = unchanged" vs "explicit null = clear" in the update path

## 4. Tests

- [x] 4.1 Unit: pace line arithmetic at window start, midpoint, end, and past reset
- [x] 4.2 Unit: each gate in isolation; conjunctive combination; margin `0` boundary
- [x] 4.3 Unit: `burn_first` cannot re-admit a gated account
- [x] 4.4 Unit: all-gated pool returns the pace-gate error
- [x] 4.5 Unit: missing reset timestamp does not exclude
- [x] 4.6 API: validation rejects out-of-range margins; explicit null clears a gate
- [x] 4.7 Migration: upgrade + downgrade round trip

## 5. Docs

- [x] 5.1 `docs/` page for pace gates linking back to
      `openspec/specs/account-routing/`
- [x] 5.2 Worked example: "only in the 2h before the 5h reset, below the 5h pace line,
      and 20 points below the weekly pace line"

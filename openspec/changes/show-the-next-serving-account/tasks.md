# Tasks

## 1. The pin becomes its own field

- [x] 1.1 Add `accounts.pinned` to `app/db/models.py` and drop `PINNED` from
      `AccountRoutingPolicy`
- [x] 1.2 Migration `20260811_000000_add_account_pinned_flag`: add the column,
      carry `routing_policy='pinned'` rows onto the flag (landing them on
      `normal`, which is what the old pin path itself wrote), and fold the flag
      back into the policy on downgrade
- [x] 1.3 `AccountRepository.set_pinned` — set the flag, clear it from the
      provider's other accounts, leave every routing policy untouched
- [x] 1.4 Stop `update_routing_policy` special-casing the pin, and reject
      `pinned` in the routing-policy request schema
- [x] 1.5 `AccountService.set_pinned`, invalidating the selection cache
- [x] 1.6 `PUT /api/accounts/{id}/pin`, echoing the routing policy back
- [x] 1.7 Carry `pinned` through the account summary schema and mapper

## 2. Selection reads the flag

- [x] 2.1 `AccountState.pinned`, and `is_pinned` reads it instead of the policy
- [x] 2.2 Pass `pinned` at every `AccountState` construction site in
      `app/modules/proxy/load_balancer.py`
- [x] 2.3 Drop the pin exemption from the additional-quota override — it was
      guarding a path the pin already wins

## 3. The pool answers who serves next

- [x] 3.1 `LoadBalancer.preview_next_account` — load the same inputs, build the
      same states, run the same pure selector with `deterministic_probe=True`,
      take no lease and write nothing
- [x] 3.2 `_RANDOMIZED_ROUTING_STRATEGIES` and the `certain` flag, exact when a
      pin decides the outcome
- [x] 3.3 `preview_next_account` on both `ProxyService` and
      `AnthropicProxyService`, each asking its own balancer with its own
      settings-derived strategy
- [x] 3.4 `GET /api/accounts/next-up`, declared above `/{account_id}/trends` so
      the literal path is not captured as an account id, and tolerant of one
      provider failing

## 4. Dashboard

- [x] 4.1 Pin toggle in `account-actions.tsx`, separate from the policy select;
      remove `pinned` from the select's options
- [x] 4.2 `pinned` in the account schemas; drop it from the routing-policy enums
- [x] 4.3 `updateAccountPin` in `api.ts` and a mutation in `use-accounts.ts`
- [x] 4.4 Replace `servingAccountIds` with the next-up query; mark the named
      account, and say "Likely next" when the answer is uncertain
- [x] 4.5 Render the pin beside the routing policy in `account-list-item.tsx`
- [ ] 4.6 Before/after screenshots on the PR

## 5. Menu bar

- [x] 5.1 `cmdSwitch`/`cmdAuto` in `scripts/swiftbar/claudex-lb.1m.ts` write the
      pin endpoint instead of a routing policy
- [x] 5.2 Read the next-up endpoint and mark that account, instead of reading
      the newest request log row

## 6. Tests

- [x] 6.1 `tests/integration/test_account_pin_migration.py` — an existing pin
      survives the upgrade, the upgrade is re-runnable, the downgrade hands the
      pin back
- [x] 6.2 `tests/integration/test_accounts_api_routing_policy.py` — unpinning
      restores the policy the account already had, and `pinned` is rejected as a
      policy
- [x] 6.3 `tests/unit/test_next_account_preview.py` — a pin is next over an
      emptier peer, a paused account never is, the answer is stable, and the
      uncertain flag matches the strategies that actually draw at random
- [x] 6.4 Port the pin's own suite and the balancer factories to the flag
- [x] 6.5 Frontend: next-up rendering and the pin toggle

## 7. Review fixes

An adversarial review over the diff (five dimensions, every finding
independently verified) surfaced these before the change shipped:

- [x] 7.1 `accounts.pinned` used `text("0")` in the model against `false()` in
      the migration. PostgreSQL renders those as `DEFAULT 0` and `DEFAULT
      false`, so the startup drift check compares a boolean to an integer and
      the app refuses to boot. SQLite hid it. Both now use `false()`.
- [x] 7.2 The preview shared `self._runtime` with the serving pool, and
      `_build_states` writes health-tier bookkeeping into whatever runtime it is
      handed — a dashboard poll could latch an account into `draining` and steer
      real traffic. It now builds from a copy of the runtime entries.
- [x] 7.3 The preview called the bare `select_account` while both serving paths
      call `_select_account_preferring_budget_safe`, so it named accounts the
      relay deliberately skips (the budget filter is wrapper-only). It now runs
      the same selector with the same thresholds and quota-planner costs.
- [x] 7.4 `certain` was read from "is anything in the pool pinned" rather than
      "did the pin decide". A pinned account that cannot serve leaves the pool
      ranking normally, so the preview reported a random draw as a certainty in
      exactly the case the pin exists for. Now read from the selected account,
      with a single-candidate pool also exact.
- [x] 7.5 The `single_account` preview echoed the configured id without checking
      whether that account could serve — and the list replaces the status badge
      with the next-up badge, so a paused seat would have lost its "paused" mark
      and read as "Next". It now runs the real selector scoped to that id.
- [x] 7.6 Menu bar: a server still storing the legacy `routing_policy='pinned'`
      showed "Auto" over a hard-pinned pool and Auto cleared nothing; an
      explicit "nobody can serve" answer was treated as no answer and fell
      through to naming the pinned account; `cmdSwitch` reactivated before
      pinning, leaving a half-applied switch when the pin write failed.
- [x] 7.7 Redeeming a rate-limit reset credit did not invalidate the next-up
      query, though it is the mutation that flips an account back to `active`.
- [x] 7.8 Coverage: `GET /api/accounts/next-up` had no route-level test at all,
      and "a preview leaves no trace" / "one provider failing does not hide the
      other" were prose only. Added
      `tests/integration/test_accounts_next_up_api.py`, and verified the
      no-trace test fails when the runtime copy is removed.

## 8. Verification

- [x] 8.1 `uv run pytest` and `bun run test` green
- [ ] 8.2 Deploy, then confirm against live: the dashboard names the account the
      next request actually lands on, and unpinning an account leaves its policy
      where it was

## 9. Sequencing note

- [ ] 9.1 This change's `account-quota-presentation` delta supersedes the
      last-served indicator from `surface-serving-account-and-pace-gates`. Sync
      that change first if both are pending, so the newer definition is the one
      that lands in the main spec.

## Why

Whether an account is presented as a subscription (rolling five-hour and weekly
windows) or as usage-based (a dollar budget) is currently inferred from which
usage rows happen to exist. That inference is right most of the time and wrong
in the moments that matter:

- An account polled before its first budget read has no budget row yet, so it
  presents as a subscription with two empty window bars.
- An account that once reported windows and later moved to usage-based billing
  keeps both, and presents as a subscription forever.
- An enterprise seat that reports neither presents as a subscription with
  nothing in it, which reads as "broken" rather than "not applicable".

In every one of those the operator knows the answer and the system does not.
Nothing lets them say so.

## What Changes

- Accounts gain a `quota_kind` of `auto`, `subscription`, or `usage_based`.
- `auto` is the default and preserves today's inference exactly, so no existing
  account changes and no installation has to configure anything.
- An explicit kind wins over the inference. A `usage_based` account presents its
  budget and credits and never window bars; a `subscription` account presents
  its windows and never a budget bar in their place.
- An explicit kind that has no data to show says so rather than falling back to
  the other presentation, because a setting that silently reverts is worse than
  no setting.
- The dashboard exposes the choice per account, next to the routing policy.

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `account-quota-presentation`: which quota surface an account presents becomes
  an account setting with an inferring default, rather than a fact derived only
  from which usage rows exist.

## Impact

- Code: `app/db/models.py`, `app/modules/accounts/{schemas,mappers,repository,service,api}.py`
- Migration: `20260812_010000_add_account_quota_kind` — adds the column defaulted
  to `auto`, which is the behaviour every existing row already had.
- Frontend: `frontend/src/features/accounts/{schemas.ts,api.ts,hooks/use-accounts.ts,components/account-actions.tsx,components/account-list-item.tsx,components/account-usage-panel.tsx}`
- Tests: `tests/integration/test_accounts_api_quota_kind.py`,
  `frontend/src/features/accounts/**/*.test.{ts,tsx}`
- Specs: `openspec/specs/account-quota-presentation/spec.md`

## Simplicity

No new `CODEX_LB_*` setting: this is per-account state, and it defaults to
`auto`, which is exactly what the system does today. An operator who never opens
the control never notices it exists. It adds one column and one endpoint, and
removes the situation where the only way to fix a mispresented account is to
wait for the right usage row to arrive.

## Why

ChatGPT now meters Codex and ChatGPT chat against the same plan allowance, and Claude
has always metered Claude Code and claude.ai chat together. A pooled Plus or Pro seat that
belongs to someone who only chats is therefore no longer "spare Codex capacity": every
token the pool spends on it comes out of the allowance its owner uses for chat. Run that
seat to 100% and its owner is locked out of their own subscription until the window
resets.

The existing controls do not express "use this seat, but never past 80%":

- Pace gates bound the *rate* of consumption relative to time left in a window. At the
  end of a window the pace line reaches 100%, so a paced account can still be drained
  completely.
- `preserve` only lowers an account's rank; it is still drained once the others are.
- The pre-reset window ("use up before reset") deliberately spends what is left.

There is also no way for two devices on the same pool to disagree about an account. A
laptop that should keep a friend's seat in reserve and a desktop that may finish the
operator's own seat share one set of per-account settings today.

## What Changes

- Two optional per-account **usage ceilings**, `usage_ceiling_primary_pct` (5h) and
  `usage_ceiling_secondary_pct` (weekly), each unset by default. Once a window's recorded
  usage reaches its ceiling, the account leaves the selection pool until that window
  resets. Ceilings are hard eligibility filters like pace gates, and unlike pace gates a
  pin does not lift them.
- Optional **per-API-key account routing rules**. For each account, a key may override
  the routing policy (`burn_first` / `normal` / `preserve`) and may replace the account's
  ceilings and pace gates with its own set, in which an unset value switches that gate
  off for the key. Keys without rules, and accounts a key has no rule for, behave
  exactly as before.
- The dashboard account API reads and writes the ceilings through the existing
  `PUT /api/accounts/{id}/pace-gates`. The API-key API returns `accountRoutingRules` and
  gains `PUT /api/api-keys/{id}/account-routing-rules`.
- The dashboard edits both; the menu bar edits ceilings and marks an account held at
  its ceiling.

## Capabilities

### Modified Capabilities

- `account-routing`: per-account usage ceilings; per-API-key routing rules.

## Impact

- Code: `app/core/balancer/{logic,routing_rules}.py`, `app/modules/proxy/load_balancer.py`,
  the three selection call sites in `app/modules/proxy/service.py`, the Anthropic relay,
  `app/modules/accounts/*`, `app/modules/api_keys/*`, `app/db/models.py`
- Migration: two nullable columns on `accounts`, new table `api_key_account_routing_rules`
- Dashboard: account actions panel, usage bars, API-key routing editor
- Menu bar: `ceiling` subcommand and per-account presets
- Docs: `docs/usage-ceilings.md`

## Simplicity

No new `CODEX_LB_*` settings and no new README section. Every new field is nullable and
unset by default, and the rules table starts empty, so an installation that never
touches the feature keeps its selection behavior byte for byte. No new dashboard nav
item: the controls live in the existing account panel and API-key dialog.

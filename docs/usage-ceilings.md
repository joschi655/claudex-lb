# Usage Ceilings and Per-Key Routing

A usage ceiling caps how much of a window the pool may take from an account. Per-key routing
rules let each API key, and so each device, rank and limit the same accounts differently.

Both are off by default. An installation that never configures them behaves exactly as before.

## Why cap an account below 100%

ChatGPT meters Codex and ChatGPT chat against the same plan allowance, and Claude meters Claude
Code and claude.ai chat together. A shared Plus seat whose owner only chats is not spare
capacity: whatever the pool spends comes out of the allowance the owner uses every day. Run it
to 100% and the owner is locked out of their own subscription until the window resets.

A ceiling keeps the rest of the window for them. Typical reasons to set one:

- **Someone else's seat.** A friend or family member lends a Plus seat but still chats on it.
  A weekly ceiling of 70–80% leaves them a working allowance.
- **Your own chat headroom.** You want Codex to use your seat, but not so hard that ChatGPT
  or claude.ai stops answering in the middle of the afternoon.
- **A reserve for emergencies.** One account stays below 90% so there is always something to
  fall back on when the others run out.
- **Keeping the account in good standing.** A seat that is never pinned to its limit looks
  like ordinary use.

## Usage ceilings

| Field | Effect |
|---|---|
| `usageCeilingPrimaryPct` | Stop serving from this account once its 5h usage reaches this %. |
| `usageCeilingSecondaryPct` | Stop serving from this account once its weekly usage reaches this %. |

Values must be greater than `0` and at most `100`. Leave a field empty, or send `null`, to
switch that ceiling off.

```bash
curl -X PUT https://your-proxy/api/accounts/<account-id>/pace-gates \
  -H 'Content-Type: application/json' \
  --cookie "$DASHBOARD_SESSION" \
  -d '{ "usageCeilingSecondaryPct": 80 }'
```

In the dashboard the fields sit under **Usage ceiling** in the account panel, with Off / 80 /
90 / 95 presets, and each usage bar shows a marker where the ceiling sits. In the menu bar each
account has **Stop at (5h)** and **Stop at (7d)** presets, and an account that is being held
shows `🛑 at 7d ceiling`.

### How a ceiling differs from the other controls

| Control | What it bounds | Can the account still reach 100%? |
|---|---|---|
| `preserve` policy | rank only | yes, once the other accounts are spent |
| [Pace margin](pace-gates.md) | rate, relative to time left in the window | yes, at the end of the window |
| Pre-reset window | when the account may serve | yes, that is its purpose |
| **Usage ceiling** | absolute share of the window | **no** |

They combine with AND. A weekly pace margin of 10 with a weekly ceiling of 80 follows the pace
line minus 10 points until 80%, then sits out until the week resets.

### Rules

- **Hard filter.** An account at its ceiling leaves the selection pool before any ranking runs.
  `burn_first`, fallbacks and session stickiness cannot bring it back.
- **A pin does not lift it.** A [pinned](account-pin.md) account ignores pace gates, but it
  stops at its ceiling and the pool picks the next account. The ceiling is a promise to the
  account's owner, not to yourself.
- **Unknown usage never blocks.** A freshly added account without usage data is not held back,
  and neither is an account whose last sample comes from a window that has already reset.
- **It is a target, not a guarantee to the decimal.** The ceiling is checked when a request
  picks an account. Requests already running finish where they are, so usage can end slightly
  above it — a fraction of a point in a weekly window, a few points in a busy 5h window.
- **When every account is held**, requests fail with
  `All accounts are held at their usage ceilings (…)` rather than spending anyone's reserve.

## Per-key routing rules

Give each device its own [API key](api-keys.md), then tell each key how to treat each account.
For every account, a key can:

- **Change its priority** — *Use first* (`burn_first`), *Normal*, or *Use last* (`preserve`) —
  for this key only.
- **Use its own limits** — replace the account's ceilings, pace margins and pre-reset window
  with a set of its own. In that set an empty field means *off for this key*.

Accounts a key has no rule for, and keys without rules, use the account's own settings.
Rules never change *which* accounts a key may reach; that is still the key's account
assignment.

### Example

You have your own Pro seat and a friend's Plus seat with a weekly ceiling of 80%.

| Device | Rule | Result |
|---|---|---|
| Laptop | none | Shares both seats normally and stops the friend's at 80%. |
| Desktop | your Pro seat: *Use first*, own limits with everything off | Spends your Pro seat first and to 100%, and still stops the friend's seat at 80%. |

```bash
curl -X PUT https://your-proxy/api/api-keys/<desktop-key-id>/account-routing-rules \
  -H 'Content-Type: application/json' \
  --cookie "$DASHBOARD_SESSION" \
  -d '{
        "rules": [
          { "accountId": "<your-pro-seat>", "routingPolicy": "burn_first", "overrideGates": true }
        ]
      }'
```

The request replaces all of the key's rules. A rule that changes nothing is dropped. In the
dashboard the editor is under **Account routing** on each key.

---

*Spec: [account-routing](https://github.com/joschi655/claudex-lb/tree/integration/claude-live/openspec/specs/account-routing)*

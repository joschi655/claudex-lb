# Routing Strategy Guide

The dashboard setting **Routing strategy** controls how eligible accounts are selected for each request. No strategy can guarantee account-safety outcomes; conservative use still depends on staying within OpenAI terms, using normal request volumes, and avoiding traffic patterns that would be unusual for your accounts.

For low-volume, policy-compliant personal use, start with **Capacity weighted** or **Relative availability** and keep sticky threads enabled. Those strategies preserve session locality while avoiding sudden all-traffic shifts to a single account.

| Routing strategy | Behavior | Trade-offs and recommended use |
|---|---|---|
| Capacity weighted | Prefers accounts with more usable quota headroom. | Good default for mixed pools and normal compliant usage. |
| Relative availability | Draws from the strongest available accounts with configurable weighting. | Smooths distribution while still preferring healthier accounts. |
| Usage weighted | Reacts to observed recent usage. | Useful when usage history should influence selection, but less direct than capacity-based routing. |
| Round robin | Cycles evenly through eligible accounts. | Simple and predictable, but ignores quota shape and reset timing. |
| Fill first | Uses one account heavily before moving on. | Best for controlled drain tests; less conservative for everyday traffic. |
| Sequential drain | Drains accounts in a fixed order. | Useful for maintenance or explicit account rotation, not a normal safety-first default. |
| Reset drain | Prioritizes capacity near reset windows. | Helps consume expiring quota, but can create timing-shaped bursts. |
| Single account | Pins all traffic to one selected active account. | Useful for isolation and debugging; no load balancing. |

Change the strategy live in the dashboard under **Settings → Routing** — no restart required.

## Spend the window that closes first

With **Prefer earlier reset** on and its window set to **5h**, a new session goes to the account
whose 5h window resets soonest. Quota left in that window is used before it expires instead of
being thrown away at the reset. Established sessions stay where they are.

It orders only the accounts the earlier rules leave equal. In order of precedence:

1. Hard filters: paused or failing accounts, [usage ceilings](usage-ceilings.md), [pace gates](pace-gates.md)
2. The [account pin](account-pin.md)
3. Accounts under the budget threshold (95% by default) ahead of accounts above it, and the health tier
4. Priority: *Use first* (`burn_first`), *Normal*, *Use last* (`preserve`), including an
   [API key's own rule](usage-ceilings.md#per-key-routing-rules)
5. **Earliest 5h reset**
6. The routing strategy (for example *Fill first* picks the fuller account among equal resets)

An account with no open 5h window ranks after every account with one, so the preference does not
open fresh windows while open ones still have quota. It applies to Codex and Claude traffic alike.

---

*Spec: [account-routing](https://github.com/Soju06/codex-lb/tree/main/openspec/specs/account-routing)*

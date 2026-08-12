# Account Pin

Pinning routes every request to one account for as long as that account can serve, and hands
selection back to the automatic rules when it cannot.

Set it from the pin toggle in the dashboard's account actions, or over the API:

```bash
curl -X PUT "$CODEX_LB_URL/api/accounts/$ACCOUNT_ID/pin" \
  -H 'Content-Type: application/json' \
  -d '{"pinned": true}'
```

The pin is a field of its own, not a routing policy. An account keeps its `normal`, `burn_first`, or
`preserve` policy while pinned and goes straight back to it when the pin lifts — so pinning a
preserved seat for an afternoon does not quietly return it to the general pool. The response echoes
the account's routing policy back, which is what an unpin reports.

Pinning is exclusive within a provider: pinning an account clears the provider's previous pin in the
same write. Pinning a Claude account leaves a pinned Codex account alone, and the other way round.

## What the pin overrides

A pin is not a ranking preference. While the pinned account can serve, it is the only candidate the
selector considers — the routing strategy, the usage figures, and the other accounts are not
consulted at all.

| Rule | With a pin |
|---|---|
| Routing strategy (usage-weighted, round-robin, …) | not consulted |
| Health tier (`healthy` / `probing` / `draining`) | not consulted |
| Routing policy tiers (`burn_first`, `normal`, `preserve`) | not consulted |
| [Pace gates](pace-gates.md) and the pre-reset window | not applied to the pinned account |
| Budget thresholds | not applied to the pinned account |
| Session stickiness | the pin wins; the session moves onto it |
| Additional-quota routing policy | does not replace the pin |

## What the pin does not override

The pin decides *where* traffic goes, never *whether* an account is capable of taking it. These
still exclude the pinned account, exactly as they would any other:

- account status: `paused`, `reauth_required`, `deactivated`
- an unexpired `rate_limited` or `quota_exceeded` reset
- an active cooldown or error backoff
- model plan eligibility, and additional-quota eligibility
- an API key's account assignments — a pin outside the key's scope is not in the pool at all

## Release and resume

When the pinned account cannot serve, selection falls back to the automatic rules over the
remaining accounts. **The pin is not cleared by that.** It stays on the account and takes effect
again the moment the account recovers — when a five-hour window resets, when a cooldown expires,
when an operator unpauses it. Nothing has to be re-pinned after an exhausted window.

To stop pinning, write `{"pinned": false}`. The account's routing policy is untouched by both
writes.

## Choosing between a pin and a routing policy

`burn_first` and `preserve` answer "in what order should the pool draw from these accounts". The
pin answers "use this one". Reach for a policy when you want to bias the pool and keep failover
behaving normally; reach for the pin when you want a specific account carrying the traffic and are
content for the pool to take over only when it genuinely cannot.

A pin and a [pace gate](pace-gates.md) on the same account are not a contradiction to resolve by
hand: the gate is what the account does in the pool, the pin is the operator overriding it for now.
Unpinning restores the gate.

## Seeing where the pin landed

The dashboard account list and the menu bar name the account the **next** request will be routed to,
which is how a pin is confirmed without waiting for traffic. Ask directly with:

```bash
curl "$CODEX_LB_URL/api/accounts/next-up"
```

One entry per provider. `certain: false` means the configured routing strategy draws at random among
the accounts with capacity, so the account named is the front-runner rather than a promise; a pin
makes the answer exact. The call runs the selector as a dry run — it takes no lease, writes no
session mapping, and does not change what the next real request does.

The answer is for a *new* session. An established session follows its own sticky mapping, unless a
pin overrides it.

---

*Spec: [account-routing](https://github.com/Soju06/codex-lb/tree/main/openspec/specs/account-routing)*

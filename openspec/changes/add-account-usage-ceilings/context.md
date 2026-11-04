# Context

## Why a ceiling, and why it is not a pace margin

A pace margin answers "is this account being spent faster than its window allows?". Its
line rises from 0% to 100% across the window, so a paced account is spent completely by
the time the window closes. That is right for a seat the pool owns, and wrong for a seat
whose owner chats from the same allowance: near the end of the window the owner finds it
empty.

A ceiling answers a different question: "how much of this window may the pool take at
all?". The two compose with AND. With a weekly pace margin of 10 and a weekly ceiling of
80, the account follows the pace line minus 10 points until it reaches 80% and then sits
out for the rest of the week.

| Control | Bounds | Can still reach 100%? |
|---|---|---|
| `preserve` policy | rank only | yes, once the others are spent |
| pace margin | rate relative to time left | yes, at the end of the window |
| pre-reset window | when the account may serve | yes, that is its purpose |
| usage ceiling | absolute share of the window | no |

## Why a pin does not lift a ceiling

A pin is the operator withdrawing their own rate promise for one account, so it lifts the
pace gates. A ceiling is a promise to someone else: the account's owner keeps the rest of
the window. Pinning a friend's seat to try it out must not quietly spend their reserve, so
a pinned account at its ceiling falls through like an exhausted one, and the pool's
automatic rules pick the next account.

## Why rules live on the key and replace gates wholesale

The key is the closest thing the proxy has to "which device is asking". One rule per
(key, account) pair covers the two cases that came up in practice:

- **Rank differently.** The desktop spends the operator's own seat first (`burn_first`);
  the laptop spends the pool seats first and keeps the operator's for later (`preserve`).
- **Limit differently.** The laptop respects the friend's 80% ceiling; the desktop belongs
  to the same operator and may use the operator's own seat to 100%.

Per-field inheritance was rejected: it needs a third state per field ("inherit" versus
"off" versus a value), which is hard to read in a form and harder to reason about when an
account's own values change later. `override_gates` gives two clear states — "this key
follows the account's limits" or "this key has its own limits, shown in full here".

Rules do not touch `api_key_accounts`. Scoping decides *whether* a key may reach an
account; a rule decides *how* it draws on it. Keeping them apart means switching a key's
scope on or off never discards its rules.

## Failure modes

- **Overshoot.** The ceiling is checked when an account is selected. Requests already in
  flight finish there, so usage can end slightly above the ceiling — usually a fraction of
  a point in a weekly window and a few points in a busy 5h window. A ceiling of 80% is a
  target, not a guarantee to the decimal.
- **Stale samples.** Usage arrives with traffic and the usage poller. A sample from a
  window that has already reset is ignored, so an account is never stranded behind a
  number from a window that no longer exists.
- **Continuations.** An established conversation whose account reaches its ceiling moves
  to another account, as it does when an account runs out. The conversation's prompt cache
  does not move with it.
- **Whole pool held.** When every account is at a ceiling, requests fail with "All accounts
  are held at their usage ceilings (…)". That is the intended outcome: the alternative is
  spending an owner's reserve.

## Example

Seat `friend@plus` is shared by a friend who uses ChatGPT daily. The operator sets a weekly
ceiling of 80% on it. The laptop key has no rule, so it follows that ceiling. The desktop
key carries a rule `{ accountId: "me@pro", routingPolicy: "burn_first", overrideGates: true }`,
so it spends the operator's own Pro seat first and to 100%, and still respects the friend's
ceiling because it has no rule for that seat.

# Context

## Why the pin could not stay in `routing_policy`

The pin shipped as a fourth routing-policy value because the column was already
there and the dropdown was already wired. That was cheap, and it was wrong in a
way that only shows up on the way *out*: pinning wrote `pinned` over whatever
the account held, so unpinning had nothing to go back to and had to guess
`normal`.

The guess is not harmless. `preserve` exists to keep a seat out of rotation
until the others are spent; demoting it to `normal` on unpin silently puts that
seat back in the general pool. An operator who pins a seat for an hour gets
their pool back subtly rearranged, and nothing in the UI says so.

The migration cannot repair the accounts this already happened to — the old
value was overwritten in the database, not shadowed. Rows that are pinned at
upgrade time are therefore migrated to `pinned=true, routing_policy='normal'`,
which is exactly the state the old code would have left them in on unpin. That
is a real, if small, data loss, and the spec says so rather than implying the
migration is lossless.

## Why "last served" is the wrong question

The old badge read the newest row of `request_logs`. That is a fact about the
past, and it is the *only* fact a request log can offer. Every case where an
operator actually looks at the badge is a case where the past has just stopped
predicting the future:

- They pinned an account and want to know the pin took.
- They paused an account and want to know traffic moved off it.
- An account hit a limit and they want to know where the pool went.

In all three the badge keeps naming the old account until new traffic arrives —
and if the pool is idle, indefinitely. Worse, it is *right* in the boring case
and wrong in exactly the interesting one, which is the failure mode that trains
an operator to trust it.

`GET /api/accounts/next-up` answers the question directly by running the real
selector as a dry run. Three details make that work, and each of them was got
wrong on the first pass:

- It runs the **same selector the relay runs** —
  `_select_account_preferring_budget_safe`, with the same budget thresholds and
  quota-planner costs. The bare `select_account` underneath it skips the budget
  filter, so a preview built on it named accounts the relay deliberately passes
  over: an account fresh on the week but burned past 95% of its five-hour window
  ranks top under `capacity_weighted` and is excluded by the filter. That is
  precisely the "window running out" shape the feature exists to show.
- It builds its states from a **copy of the runtime entries**, not the live
  ones. `_build_states` writes health-tier bookkeeping back into whatever
  runtime it is handed, so a preview sharing `self._runtime` would let a
  dashboard poll latch an account into `draining` — a status view changing where
  traffic goes. The two other read-only callers of `_build_states` pass an empty
  runtime for the same reason; a copy keeps the answer accurate as well as inert.
- It asks the **running proxy services**, not a fresh balancer. Each provider
  has its own `LoadBalancer` with its own in-memory runtime — leases, cooldowns,
  health tiers, error backoff. A preview built from the database alone would
  disagree with the pool it claims to describe.

Nothing is acquired along the way: no lease, no sticky mapping, no persisted
row. `tests/integration/test_accounts_next_up_api.py` holds that to a
whole-runtime snapshot comparison rather than a field-by-field one, so a field
added later is covered without anybody remembering to extend the test.

## The two honest caveats

**The answer can be a front-runner rather than a promise.** `capacity_weighted`
(the default) and `relative_availability` draw at random among weighted
candidates. `deterministic_probe=True` makes the preview reproducible, but the
real request still draws. Rather than hide that, the response carries
`certain: false` and the dashboard says "Likely next". Every other strategy
takes `min()` of a sort key and is exact; so is a pool with one candidate.
`tests/unit/test_next_account_preview.py` guards that list, so a strategy that
becomes randomized later cannot quietly start lying.

A pin makes the answer exact — but only when the pin *decided* it. Reading
certainty as "is anything in the pool pinned" was the first attempt, and it is
wrong in the one case that matters: the selector applies the pin over the
accounts that survived eligibility, so a pinned account that is rate limited
leaves the pool ranking normally while the flag still claimed a certainty. That
is the pinned window running out — the exact moment an operator looks. Certainty
is therefore read from the account that came back, never from the pool that went
in.

**The answer is for a new session.** An established session follows its own
sticky mapping. The preview deliberately does not take a session id: "which
account serves next" is a question about the pool, and answering it for one
caller's session would make the dashboard's answer depend on who is asking.

## What the menu bar had to change

`cmdSwitch` and `cmdAuto` wrote `routing_policy="pinned"` and cleared it back to
`normal` — which is precisely the lossy path this change removes. They now call
the pin endpoint, so switching seats from the menu bar no longer flattens a
`preserve` seat into `normal` on the way back.

# Context

## What the number means, and a decision reversed

These are subscription seats, not API keys. Nobody is invoiced for a request the
proxy relays, so the figure is notional: what this traffic would have cost at
published API rates. The point of it is comparing what a seat produces against
what it would cost to buy, and seeing which model and which cache behaviour the
spend is going to.

`add-anthropic-request-logs` decided the opposite, deliberately: "Populating
list-price figures was considered as a 'what this would have cost on the API'
signal and rejected — it would show spending that never happened, in the same
column the Codex rows use for money actually owed." This change reverses that,
and the reason is that the premise does not hold. The Codex rows on this
deployment are ChatGPT subscription seats, not API keys, and they are priced at
list rates in exactly that column — $304 of `gpt-5.6-sol` that nobody was
invoiced for. The column already means "list-rate cost of the tokens", for
subscription seats and API keys alike. Leaving Claude out did not keep the
column honest; it made the same column mean one thing for one provider and
another for the next, and reported half the traffic as free.

The earlier note suggested that if the comparison were wanted it should get its
own field. That was the right instinct under its premise and is the wrong shape
under this one: a second field would not reach the cost-per-day chart, the
per-account donut, or any total, which is where the question is actually asked.

## Why cache writes needed a column

Anthropic reports three disjoint input counters and bills them at three rates:

| Counter | Rate |
|---|---|
| `input_tokens` (uncached) | base |
| `cache_read_input_tokens` | 0.1x base |
| `cache_creation_input_tokens` (5-minute TTL) | 1.25x base |

`request_logs` stores a total and one subset: `input_tokens` is the sum of all
three, `cached_input_tokens` is the cache reads. The cost path then prices the
difference as uncached input. That works while there are two rates, and stops
working at three — a cache write is arithmetically indistinguishable from
uncached input once stored, so it is necessarily charged at the base rate.

The error is not academic on this traffic. Of 1.15 billion Claude input tokens on
the deployment that prompted this change, 1.03 billion are cache reads; most of
the remaining 115 million are cache writes. Charging those at 1.00x instead of
1.25x under-reports by roughly 10% of the total bill. Recovering it needs the
counter kept, which is why this change adds a column rather than only a rate
table.

The counter is nullable rather than defaulted to zero, so a row written before
the column existed stays distinguishable from a request that genuinely wrote
nothing to cache. Both price the same way; only one of them is a measurement.

## What the backfill can and cannot repair

The migration recomputes `cost_usd` for Anthropic rows that have none, from the
tokens those rows already store. Without it, the aggregate views stay at zero for
all historical Claude usage while the detail view — which recomputes on read —
shows a price, and the two disagree on the same request.

The backfill cannot recover the cache-write split, because those rows never
stored it. Historical requests are therefore priced with every non-cache-read
input token at the base rate: the same approximation described above, applied to
the past because the data to do better was never kept. Rows written after this
change are exact. The backfill carries the rates as literal values rather than
importing the pricing module, so a later price change cannot silently rewrite
what an old migration computes.

## Rates, as published

Taken from the model pricing table on 2026-08-12. Cache-read and cache-write
rates are the documented 0.1x and 1.25x multipliers, which the published
per-model columns agree with exactly.

| Model | Input | 5m cache write | Cache read | Output |
|---|---|---|---|---|
| Fable 5 | $10 | $12.50 | $1.00 | $50 |
| Opus 5 / 4.8 / 4.7 / 4.6 / 4.5 | $5 | $6.25 | $0.50 | $25 |
| Sonnet 5 | $2 | $2.50 | $0.20 | $10 |
| Sonnet 4.6 / 4.5 | $3 | $3.75 | $0.30 | $15 |
| Haiku 4.5 | $1 | $1.25 | $0.10 | $5 |

Sonnet 5's $2/$10 is the standard price, not a discount: the increase to $3/$15
that was scheduled for 2026-09-01 was cancelled. Pricing it at $3/$15 would
overstate every Sonnet request by half.

Claude 4.6 and later include the full 1M-token context window at standard
pricing, so unlike `gpt-5.4` these entries carry no long-context threshold. Using
one would invent a premium that does not exist.

## Deliberately not modelled

**The 1-hour cache TTL.** Its writes cost 2x base rather than 1.25x. Anthropic
reports the split under `cache_creation.ephemeral_1h_input_tokens`, but the
relay's accumulator reads the flat `cache_creation_input_tokens` total, and
Claude Code writes 5-minute entries. A request that used 1-hour caching is
under-priced on its writes; distinguishing the two means carrying a fifth
counter, which is not worth it until traffic shows 1-hour writes.

**Fast mode.** `speed: "fast"` prices Opus 5 and Opus 4.8 at $10/$50 instead of
$5/$25 — a 2x swing, larger than anything else described here. It is left out
because it is not clear the flag survives the subscription path: fast mode is
documented as a first-party API preview, and nothing in a response confirms
whether a request was served fast. Pricing on the request's `speed` field would
be a guess in either direction, and the honest fix is evidence rather than a
default. The existing tier machinery already accepts `"fast"` as a service tier,
so adding the rates later is a price-table edit, not a redesign.

## Sequencing

The `anthropic-provider` delta here ADDs a requirement to a capability that is
still an unsynced change (`add-anthropic-request-logs`). Sync that change first
so its "Anthropic input counters map to total-and-subset columns" requirement
lands before this one extends it; the two are consistent either way, but read in
the wrong order the counter appears without the columns it partitions.

## ADDED Requirements

### Requirement: Cache-write tokens are recorded as their own counter

The relay SHALL record `cache_creation_input_tokens` as a counter of its own on
the request log, in addition to the total-and-subset columns it already writes.

`input_tokens` SHALL keep its existing meaning as the total prompt size, and
`cached_input_tokens` SHALL keep its existing meaning as the cache reads alone.
The cache-write counter is therefore the third disjoint part of the total, and
the uncached input is what remains after both are subtracted.

The counter SHALL be absent rather than zero when the response reports no cache
creation, so that a row written before this counter existed is distinguishable
from a row whose request genuinely wrote nothing to cache.

#### Scenario: Split counters are recorded in full

- **WHEN** a response reports `input_tokens=10`, `cache_read_input_tokens=90`,
  and `cache_creation_input_tokens=5`
- **THEN** the logged row records `input_tokens=105`, `cached_input_tokens=90`,
  and `cache_write_input_tokens=5`

#### Scenario: A response without cache creation records no counter

- **WHEN** a response reports no `cache_creation_input_tokens`
- **THEN** the logged row records no cache-write counter

#### Scenario: A streamed response carries the counter through

- **WHEN** the relay streams a response whose `message_start` reports cache
  creation tokens
- **THEN** the logged row records them
- **AND** later events that omit the counter do not erase it

## MODIFIED Requirements

### Requirement: Subscription requests are priced at list rates

A relayed request SHALL record `cost_usd` whenever its model resolves to a
pricing entry, on the same basis as every other provider: the published rate for
the model and the tokens the response reported.

For a subscription seat the figure is what the request would have cost at list
rates, not a charge that was incurred. That is already the meaning the column
carries for subscription seats of other providers, which are priced this way
today, so recording it for Claude makes one column mean one thing rather than
two. A model with no pricing entry SHALL still record no cost.

This supersedes the earlier rule that Claude rows carry no cost. That rule read
the column as money owed, which it is not for any subscription seat, and its
effect was that Claude traffic reported as free in every total, chart, and
per-account breakdown while comparable traffic on another provider did not.

#### Scenario: A Claude completion records its list-rate cost

- **WHEN** a Claude model with a pricing entry completes successfully through
  the relay
- **THEN** the logged row's `cost_usd` is the list-rate cost of its tokens

#### Scenario: An unpriced model still records no cost

- **WHEN** a model with no pricing entry completes through the relay
- **THEN** the logged row's `cost_usd` is null

## ADDED Requirements

### Requirement: Claude model pricing is recognized

The system MUST recognize Claude model pricing when computing request costs, so
that a completed Anthropic request is priced rather than recorded as costless.

Pricing MUST be resolved from the model the response reports. Snapshot-dated
model identifiers MUST resolve to the canonical price-table entry for the same
model family, and where two entries would both match, the more specific one MUST
win.

Claude 4.6 and later models are priced at a single rate across the full context
window. The system MUST NOT apply a long-context premium to them.

#### Scenario: A Claude request is priced at its published rates

- **WHEN** a request for a Claude model completes with input and output tokens
- **THEN** the system computes a non-zero cost from that model's published rates

#### Scenario: A snapshot-dated model resolves to its family

- **WHEN** a request reports a snapshot-dated Claude model identifier
- **THEN** the system prices it using the canonical entry for that model family

#### Scenario: A large Claude request keeps standard rates

- **GIVEN** a Claude model whose full context window is priced at one rate
- **WHEN** a request for it completes with more than 200K input tokens
- **THEN** the system prices every token at that model's standard rates

### Requirement: Cache-write tokens are priced at their own rate

Prompt-cache writes are billed above the base input rate, and cache reads below
it. The system MUST therefore price a request's input from three disjoint parts:
tokens read from cache at the model's cache-read rate, tokens written to cache at
the model's cache-write rate, and the remaining uncached tokens at the base input
rate. No token may be counted in more than one part.

A model whose price table does not state a cache-write rate MUST price
cache-write tokens at its base input rate, so that models without the field are
priced exactly as they were before it existed.

The reported cost breakdown MUST expose the cache-write component alongside the
uncached-input, cache-read, and output components, so that the components account
for the total.

#### Scenario: Cache writes cost more than uncached input

- **GIVEN** a model whose price table states a cache-write rate above its base
  input rate
- **WHEN** a request completes with cache-write tokens
- **THEN** those tokens are priced at the cache-write rate
- **AND** the remaining uncached input tokens are priced at the base input rate

#### Scenario: Cache reads, cache writes, and uncached input do not overlap

- **GIVEN** a request whose total input is the sum of uncached, cache-read, and
  cache-write tokens
- **WHEN** the system prices it
- **THEN** each token is charged exactly once

#### Scenario: A model without a cache-write rate is unchanged

- **GIVEN** a model whose price table states no cache-write rate
- **WHEN** a request completes with cache-write tokens
- **THEN** those tokens are priced at the model's base input rate

#### Scenario: The breakdown accounts for the total

- **WHEN** a priced request's cost breakdown is reported
- **THEN** it names the uncached-input, cache-read, cache-write, and output
  components
- **AND** those components sum to the reported total

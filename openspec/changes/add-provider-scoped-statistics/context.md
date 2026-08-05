# Context — Provider-scoped statistics

## Decisions

**Provider is denormalized onto the row, not joined from the account.** The obvious
alternative — join `accounts` on `request_logs.account_id` and read `provider` there —
loses to one detail of the schema: that foreign key is `ON DELETE SET NULL`. Delete a
Claude account and every one of its historical rows silently becomes provider-less, which
is worst precisely where the history matters most, in the long report ranges. The repo
already answered this question once: `plan_type` is copied onto the row at write time for
the same reason. Provider follows that precedent rather than inventing a second policy for
the same class of data. The join would also put `accounts` into the query plan of the
reports aggregates, which today scan `request_logs` alone.

**Rows without an account carry `null`, not a guess.** A row can be written with no
`account_id` — a request that failed before selection, for instance. Assigning it a
provider would be an invention, and it would make "filter to Anthropic" quietly include
rows nothing Anthropic ever touched. Null keeps those rows out of both provider filters,
which is the honest answer: they belong to neither.

**The backfill defaults orphans to `openai` rather than null.** This is the one place the
two rules above are deliberately traded off. Every row that exists at migration time
predates Anthropic serving any traffic, so `openai` is not a guess about them — it is
their actual provider, whether or not the account row survives to prove it. Leaving them
null would drop the entire pre-migration history out of the OpenAI view, which is the view
that history *is*. New rows written after the migration get the strict treatment.

**No provider default in the UI.** The filter starts empty and an empty filter means the
whole pool, so an operator running a single-provider deployment never notices the feature
exists and nobody's saved dashboard state changes meaning. Defaulting to a provider would
have made the two providers' numbers correct but hidden half the traffic from someone who
did not know to look.

**Filtering is a dimension, not a separate page.** A parallel "Claude statistics" page was
considered and rejected. Every chart would be a copy, the two would drift, and the
comparison an operator actually wants — how much of the day's work went to each pool — is
easier to read by toggling a filter on one page than by holding two pages side by side.

## Why the aggregates need this

The mixing is not cosmetic. Three specific aggregates are wrong when the pool is mixed:

- **Cost per day.** Claude rows carry `cost_usd = NULL` by design (subscription seats have
  no marginal price). Summed together with Codex rows, the daily total is real money but
  the per-request average is diluted by every unpriced row.
- **Model distribution.** The donut ranks models by share of requests, so `claude-*` and
  `gpt-*` slices compete for the same 100% while drawing on entirely separate quotas.
  Neither slice tells you how loaded its own pool is.
- **Latency and tokens-per-second.** The two providers' streaming shapes differ enough
  that a mixed p95 describes no real request.

## Failure modes to watch

- **A row written before its account's provider is known.** The write path resolves
  provider from the account id; if the account was deleted between serving the request and
  writing the row, the lookup returns nothing and the row stores null. The row is still
  written — losing a log row to a bookkeeping miss would be worse than an unfiltered one.
- **Index growth.** `provider` gets its own index because the filter is the point. It is a
  low-cardinality column, so the index earns its keep only alongside the existing time
  ordering; if the request list gets slower on large PostgreSQL deployments, a composite
  `(provider, requested_at)` is the next step, not a wider single-column index.
- **Frontend filter showing an empty control.** The provider control is sourced from the
  options endpoint and hidden when fewer than two providers have traffic, so a
  single-provider deployment does not grow a control that can only be set to one value.

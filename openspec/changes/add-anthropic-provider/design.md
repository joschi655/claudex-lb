## Context

codex-lb originally assumed every account represented OpenAI OAuth credentials
and every request used an OpenAI-compatible relay. An experimental Anthropic
path added Claude.ai consumer OAuth token handling, but that creates two
problems: the credential lifecycle is unsafe when another client rotates the
same single-use refresh-token lineage, and Anthropic does not support third
parties pooling Claude.ai subscription credentials.

The platform already has useful shared infrastructure for account selection,
client API-key policy, reservations, request logs, and dashboard analytics.
Claude support should reuse those controls while making provider boundaries
structural. The change affects persisted account and log data, every shared
OpenAI-only dispatcher, the `/v1` security surface, and operator-facing setup.

## Goals / Non-Goals

**Goals:**

- Support commercial Anthropic Messages API traffic using encrypted Anthropic
  Console API keys.
- Keep one deployment and one dashboard with provider-filtered and compatible
  combined traffic analytics.
- Prevent credentials, account selection, capacity units, or provider-only
  actions from crossing provider boundaries.
- Preserve client API-key assignments, model policy, reservations, settlement,
  request logging, and bounded failover on the Anthropic relay.
- Quarantine experimental consumer-OAuth rows without destroying their history.

**Non-Goals:**

- Claude.ai Free, Pro, or Max login, OAuth token import/refresh, or subscription
  pooling.
- Translating OpenAI request schemas into Anthropic Messages requests.
- Combining OpenAI subscription credits with Anthropic API rate limits.
- Estimating Anthropic cost before an explicit pricing source is available.
- Deploying or repairing live credentials as part of the code change.

## Decisions

### Use typed provider and credential-kind columns

Every account carries `provider` and `credential_kind`; supported pairings are
validated at service and routing boundaries. Legacy Anthropic OAuth rows move
to `legacy_anthropic_oauth`, are deactivated, and keep their encrypted data for
operator-directed replacement or deletion.

This was chosen over inferring provider from token prefixes or synthetic email
addresses. Token formats are not a stable type system, inference would leave
shared call sites fail-open, and synthetic identity could merge unrelated API
keys. Destructive migration was rejected because it would discard audit and
request history without operator consent.

### Store only Anthropic Console API keys

The dashboard creates a distinct labelled row or replaces one exact Anthropic
account id. The API key is encrypted in the existing credential column and is
never returned. OAuth routes and refresh machinery reject Anthropic targets.

Consumer OAuth support was rejected because it is not an approved third-party
integration and its rotating refresh-token lineage cannot safely have both a
native Claude client and codex-lb as custodians. A separate Claude deployment
was also rejected: provider typing gives the same isolation while retaining
shared administration and analytics.

### Reuse the load balancer with mandatory provider scope

Selection, caches, assigned-account filters, and exact single-account routing
carry an explicit provider. Existing call sites default to OpenAI for backward
compatibility. Shared OpenAI fleet, refresh, warmup, quota, automation, and
reset boundaries reject or skip non-OpenAI accounts before credential use.

This keeps one mature selection implementation without allowing a Claude
request to inspect or fall back to an OpenAI account. Duplicating the entire
load balancer per provider would increase drift in reservation, health, and
assignment semantics.

### Relay canonical Messages endpoints without schema translation

`POST /v1/messages` and `/v1/messages/count_tokens` accept the original body,
reuse proxy API-key authentication and firewall controls, select an Anthropic
API-key account, strip client authentication, and inject the upstream
`x-api-key`. The body stays byte-for-byte unchanged; only policy-relevant model
and usage fields are parsed.

Canonical endpoints preserve compatibility with Claude Code and Anthropic SDKs
without maintaining a lossy OpenAI-to-Anthropic translation layer. The relay
uses bounded body reads and the existing HTTP client pool rather than adding a
new transport dependency. Count-token requests reserve no output quota. Until
an explicit Anthropic pricing source exists, requests with an applicable client
`cost_usd` limit fail closed before reservation and upstream dispatch; a zero
settlement cannot silently bypass that limit.

### Define the response-commit point as the failover boundary

Connection, TLS, response-header, and pre-first-byte failures may try another
distinct eligible Anthropic account. Once any response byte is yielded, the
request is never replayed. Each attempt owns explicit upstream cleanup and one
provider-tagged log outcome; the request owns one client reservation that is
settled after the terminal outcome. Client disconnects clean up without
degrading account health.

This favors correctness over maximum retry rate: replaying a request after the
client may have observed output risks duplicated billable work and side
effects. A `401` invalidates the exact Console key, a `429` records the best
reset metadata, and ordinary `403`/other client errors pass through without
false health changes.

### Persist provider on logs and keep capacity provider-specific

Request logs store provider independently of the account foreign key so
historical filters survive account deletion. `All` aggregates compatible
request, token, error, and latency metrics. Anthropic rate-limit headers are
stored as passive additional quota snapshots and displayed separately from
OpenAI usage windows. Unpriced Anthropic requests have null cost and make a
combined total explicitly partial.

Provider filtering is URL-backed in the dashboard so scopes are shareable and
navigation clears incompatible account/model/status filters. Keeping one
dashboard was chosen over separate applications because the underlying traffic
analytics are compatible while the UI can still isolate capacity and actions.

## Risks / Trade-offs

- **[Legacy migration selects a previously experimental row]** -> The forward
  migration assigns an unsupported credential kind and deactivates every
  Anthropic OAuth row; selection requires the supported provider/kind pair.
- **[A shared service accidentally sends an Anthropic key to OpenAI]** ->
  Provider checks sit at repository selection and shared dispatcher boundaries,
  with direct-action and batch regression tests.
- **[Failover duplicates a streamed request]** -> Account retries stop at the
  first committed response byte and only pre-commit failures are eligible.
- **[Reservations or HTTP resources leak on cancellation]** -> Settlement and
  close paths run from owned finalizers and are tested under partial failure and
  cancellation.
- **[Combined cost understates spend]** -> Unknown Anthropic costs remain null
  and set `isPartial`; they are never coerced to zero. Client `cost_usd` limits
  applicable to Claude fail closed until that usage can be priced.
- **[Anthropic rate-limit headers are incomplete or malformed]** -> Parsing is
  passive and best-effort. Missing snapshots affect presentation only, never
  request success or account validity.
- **[Console-key sharing still violates an operator policy]** -> Published
  setup documents the supported API-key boundary and makes no claim of blanket
  ToS immunity; operators remain responsible for Anthropic organization and
  key-sharing rules.

## Migration Plan

1. Back up the database and record current OpenAI/Anthropic account counts.
2. Upgrade through the provider and credential-kind migrations. Existing
   OpenAI rows backfill to `openai/openai_oauth`; request logs backfill provider
   to `openai`; experimental Anthropic OAuth rows are deactivated and marked
   `legacy_anthropic_oauth`.
3. Verify no legacy Anthropic row is active or selectable before starting
   traffic. The dashboard may still show it so an operator can replace its
   credential on the exact row or delete it.
4. Add Anthropic Console keys, create codex-lb client API keys with explicit
   Claude account/model assignments, and send a canary Messages request.
5. Confirm the request log provider, API-key settlement, client API-key
   last-used timestamp, and passive rate-limit snapshots before enabling more
   clients.
6. Keep the existing OpenAI canary path active and verify `All`, `OpenAI`, and
   `Claude` scopes independently after rollout.

Downgrade is intentionally guarded. It must refuse while supported Anthropic
API-key rows or provider-tagged data would be made ambiguous. Rollback therefore
means stopping Claude traffic, removing or exporting affected operator data as
required by the migration guard, then downgrading; production tables must not
be patched manually.

## Open Questions

None block this release. Anthropic pricing integration and richer organization
limit metadata remain future changes and must preserve null/partial-cost and
provider-specific capacity semantics until specified.

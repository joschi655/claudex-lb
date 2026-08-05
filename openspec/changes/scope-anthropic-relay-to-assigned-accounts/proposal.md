## Why

An API key can already be pinned to a subset of accounts: `api_key_accounts` holds
the assignments, `account_assignment_scope_enabled` arms them, the dashboard has a
dialog for editing them, and the Codex path narrows its candidate pool accordingly.

The Claude relay does not. `AnthropicProxyService.relay` asks the balancer for any
account of the provider and never learns which key authenticated the request, so a
scoped key silently routes across the whole Claude pool. The dashboard shows an
assignment that has no effect, which is worse than not offering one.

This matters as soon as the pool mixes seat types. A subscription seat late in its
five-hour window returns `400` the moment a request overruns what is left of its
allowance, while a usage-based seat serves the same request without complaint. An
operator who wants one client — a background agent, a long-context session — held to
the seat that can actually carry it has the assignment UI for exactly that and no way
to make it bite.

## What Changes

- The Claude relay narrows account selection to an authenticating key's assigned
  accounts whenever `account_assignment_scope_enabled` is set on that key, matching
  how the Codex path already reads the same two fields.
- Scoping is strict, as on the Codex path: when every assigned account is unavailable
  the caller gets the usual "no account available" response rather than a silent
  widening back to the full pool. A pin that quietly stops being a pin under load is
  not a pin.
- A key with scoping disabled, a key with an empty assignment set, and an
  unauthenticated request (proxy auth off) all keep today's whole-pool selection.
- Failover still applies *within* the scope: a scoped key with several assigned
  accounts fails over between them exactly as an unscoped one does across the pool.

## Impact

- Affected specs: `anthropic-provider`
- Affected code: `app/modules/anthropic_proxy/api.py`,
  `app/modules/anthropic_proxy/service.py`
- No schema change, no new setting, no migration — the columns and the editing UI
  already exist. Behavior changes only for keys that already have scoping armed,
  which the Claude relay was ignoring.

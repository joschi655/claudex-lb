## Why

With "prefer earlier reset" on and the window set to `primary`, Codex traffic spends the
account whose 5h window closes first, so the quota left in that window is used before it
expires instead of being thrown away at the reset. Claude traffic ignored the setting: the
Anthropic relay and its next-account preview passed only the routing strategy to the load
balancer, so a Claude pool kept filling or balancing as if the preference were off.

## What Changes

- The Anthropic relay and the Claude next-account preview pass the configured
  earlier-reset preference and reset window into the load balancer, like every Codex
  selection surface already does.
- Ordering is unchanged: hard filters (status, usage ceilings, pace gates), the pin, the
  health tier and the routing-policy tier (`burn_first` / `normal` / `preserve`, including a
  key's own rule) all still come first. The reset preference only orders accounts those
  rules leave equal.

## Capabilities

### Modified Capabilities

- `account-routing`: reset-window preference propagation covers the Anthropic relay.

## Impact

- Code: `app/modules/anthropic_proxy/service.py`
- Tests: `tests/integration/test_anthropic_proxy.py`, `tests/unit/test_anthropic_proxy_service.py`
- No new setting, no migration. Installations with the preference off are unaffected.

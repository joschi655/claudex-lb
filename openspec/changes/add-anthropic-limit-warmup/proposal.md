## Why

A Claude subscription's five-hour window does not run on a clock the pool controls: it
opens on the account's first request and closes five hours later. An account left idle
therefore keeps an old, nearly-spent window alive indefinitely, and the pool cannot use
it until something spends a request to start a fresh one.

codex-lb already solves this for Codex accounts. `limit_warmup` sends a one-token ping
when a window has run down or elapsed, so the next real request meets a full window
instead of the tail of an old one. Claude accounts get none of it: the sender speaks only
the ChatGPT Responses protocol, and `_ordered_usage_refresh_accounts` filters Anthropic
rows out of the loop that drives it, so no Anthropic account is ever evaluated.

Operators worked around this by hand — pinging each account from a laptop to open its
window — which only works while someone is at the laptop, and not at all for accounts
whose credentials now live on the server.

## What Changes

- `limit_warmup` gains an Anthropic sender: a `max_tokens: 1` `POST /v1/messages` against
  the cheapest Claude model, sent with the account's own OAuth credential through the
  same auth path the relay uses.
- The warmup sender is selected by `account.provider`, so one scheduler drives both
  providers and the existing thresholds, cooldowns, and attempt records apply unchanged.
- Anthropic accounts are evaluated for warmup from their **stored** window state rather
  than a usage poll. Anthropic publishes no usage API to poll; the reset timestamp
  recorded from the last served request already says when the window closes, and each
  warmup ping's response headers refresh it, so the cycle sustains itself.
- A warmup ping ingests the unified rate-limit headers from its own response, so the
  newly opened window is visible immediately rather than at the next real request.
- `POST /api/accounts/{account_id}/limit-warmup/trigger` fires a warmup on demand for a
  single account, so a menu-bar client can open a window without waiting for the
  scheduler.
- Accounts that report no five-hour window — usage-based enterprise seats, which bill
  against a dollar budget and have no window to open — are skipped rather than pinged.

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `anthropic-provider`: Claude accounts become participants in limit warmup, with the
  window-elapsed trigger and the on-demand endpoint documented as relay-adjacent
  behavior.

## Impact

- Code: `app/modules/limit_warmup/service.py` (provider dispatch, Anthropic sender),
  new `app/core/anthropic/warmup.py`, `app/core/usage/refresh_scheduler.py` (Anthropic
  evaluation pass), `app/modules/accounts/api.py` + `service.py` (trigger endpoint).
- Migration: none. `account_limit_warmups` and the `limit_warmup_*` settings are already
  provider-neutral.
- Tests: `tests/unit/test_anthropic_warmup.py`,
  `tests/integration/test_anthropic_limit_warmup.py`.
- Specs: this change's deltas; `add-anthropic-request-logs` is the sibling change that
  introduced relay-side header ingestion.

## Simplicity

No new `CODEX_LB_*` settings. Warmup stays off by default and is governed by the existing
global `limit_warmup_enabled` plus the existing per-account toggle, so an install that
never enables it sees no behavior change at all. The Anthropic warmup model is a constant
rather than a setting: the requirement is "the cheapest model that opens a window", which
has one right answer and nothing to tune. The on-demand endpoint reuses the account
router's existing dashboard-session auth and adds no new authentication surface.

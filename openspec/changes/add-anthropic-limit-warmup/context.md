# Context — Anthropic limit warmup

## What a warmup actually does

It is not a health probe and not a usage refresh. A Claude five-hour window opens on the
account's **first** request and closes five hours later regardless of what happens in
between. An account nobody touches keeps whatever window it last opened, so an account
that ran to 95% at noon is still at 95% at midnight until something spends one request to
start the next window.

The ping is that one request. Its content is irrelevant — `max_tokens: 1` against the
cheapest model, one word in, one token out. What matters is that it lands, because
landing is what starts the clock.

## Decisions

**Eligibility comes from stored state, not a poll.** The Codex path warms accounts as a
side effect of the usage refresh loop, which polls ChatGPT's usage API and compares
before/after snapshots. Anthropic publishes no equivalent endpoint to the proxy, which is
why `_ordered_usage_refresh_accounts` excludes Anthropic accounts in the first place.

Polling is also unnecessary here. The reset timestamp already recorded from the last
served response says exactly when the window closes; once that moment passes, the window
is elapsed. And because a warmup response carries fresh headers, each ping rewrites the
timestamp five hours forward — the trigger keeps re-arming itself without any external
source of truth.

**The warmup model is a constant, not a setting.** `limit_warmup_model` exists on the
Codex side because Responses models differ meaningfully in cost and availability per
plan. For this purpose there is exactly one sensible Claude choice — the cheapest model
that opens a window — and no operator has a reason to prefer another. A second setting
would be a knob with one correct position.

**Usage-based seats are excluded rather than special-cased.** An enterprise usage-based
seat has no five-hour window at all: its responses carry overage headers instead of
window utilization, and it bills against a dollar budget that resets on a billing cycle
the proxy does not control. Warming it would spend budget to open a window that does not
exist. The exclusion falls out of the eligibility rule — no recorded five-hour window
means no elapsed window — rather than needing a seat-type check, which keeps the rule
honest for any future plan shape that behaves the same way.

**A failed warmup is not an account-health event.** Warmup is discretionary traffic. If
the ping fails, the account is no worse off than before it was attempted, and the pool
should not lose a serving account because a background nicety errored. The attempt row
records the failure so a systematically failing account is visible; nothing else changes.
This mirrors the Codex path, where warmup failures are likewise inert.

**The on-demand trigger is deliberately independent of the scheduler switch.** The point
of the endpoint is manual control from a menu bar: open this account's window, now,
because I am about to use it. Requiring the global automatic setting to be on before a
manual action works would conflate two different decisions — "warm my accounts for me"
and "warm this one now".

## Failure modes

- **Ping succeeds, headers absent.** Some responses carry no rate-limit headers. The
  attempt is still a success — the window opened whether or not the response described
  it — and the next served request will report the state.
- **Credential needs refreshing.** Handled by the shared auth path before the request is
  built; a refresh failure surfaces as the same reauth outcome a relayed request would
  produce, not as a warmup-specific status.
- **Two nodes warm the same account.** The existing attempt table's uniqueness constraint
  on account + window + reset timestamp keeps a single attempt per window, which is why
  warmup reuses it rather than tracking Anthropic attempts separately.
- **Clock skew on the reset timestamp.** The trigger reads a timestamp the upstream
  produced. A window judged elapsed slightly early costs one wasted token; judged late,
  the next warmup evaluation catches it.

## Example

An account last served at 09:10, and its response reported a five-hour window resetting
at 14:10.

- 09:10–14:10 — evaluations see a future reset timestamp and do nothing.
- 14:10 — the window closes. The next evaluation finds the timestamp in the past, warmup
  is enabled for the account, and a ping goes out.
- The ping's response reports 0% utilization with a reset at 19:10, which is ingested as
  the account's new five-hour window.
- The pool now sees a full window on an account nobody has used, and the next evaluation
  sees a future timestamp again.

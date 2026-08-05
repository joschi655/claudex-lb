# Tasks

## 1. Anthropic warmup sender

- [x] 1.1 New `app/core/anthropic/warmup.py` with the fixed warmup model, the minimal
      request body, and a `send_warmup(...)` that posts `/v1/messages` with an OAuth
      bearer and returns status, latency, token usage, and the response headers
- [x] 1.2 Parse the response's unified rate-limit headers via the existing
      `app/core/anthropic/usage_headers.py` parser rather than a second implementation
- [x] 1.3 Treat a `4xx`/`5xx` as a failed attempt carrying the upstream error code, never
      as an account-health signal

## 2. Provider dispatch in limit warmup

- [x] 2.1 Add `AnthropicLimitWarmupSender` implementing the existing `LimitWarmupSender`
      protocol
- [x] 2.2 Add a dispatching sender that picks the OpenAI or Anthropic sender from
      `account.provider`; wire it where `StreamingLimitWarmupSender` is constructed today
- [x] 2.3 Resolve the warmup model per provider so the Codex setting never reaches a
      Claude request

## 3. Eligibility and scheduling

- [x] 3.1 Anthropic eligibility helper: enabled globally + per account, provider is
      Anthropic, status can serve, a five-hour window has been recorded, its reset
      timestamp has passed, and the cooldown has elapsed
- [x] 3.2 Evaluate Anthropic accounts in the background refresh loop without routing them
      through the ChatGPT usage poll
- [x] 3.3 Ingest the warmup response's usage snapshot for the warmed account

## 4. On-demand trigger

- [x] 4.1 `AccountsService.trigger_limit_warmup(account_id)` returning the attempt outcome
- [x] 4.2 `POST /api/accounts/{account_id}/limit-warmup/trigger` on the accounts router,
      with request/response schemas
- [x] 4.3 Reject ineligible accounts with a client error naming the reason; allow the
      trigger while scheduled warmup is disabled

## 5. Tests

- [x] 5.1 `tests/unit/test_anthropic_warmup.py`: request shape, header parsing, error
      mapping
- [x] 5.2 Dispatch test: an Anthropic account never reaches the Responses sender and a
      Codex account never reaches the Messages sender
- [x] 5.3 Eligibility tests: elapsed window warms, future window does not, no-window
      account is skipped, cooldown holds, disabled toggles hold
- [x] 5.4 `tests/integration/test_anthropic_limit_warmup.py`: the trigger endpoint sends a
      warmup, returns the outcome, refuses an ineligible account, and works with
      scheduled warmup off
- [x] 5.5 A failed warmup leaves account status unchanged

## 6. Docs

- [x] 6.1 `context.md` for the decisions that are not requirements
- [x] 6.2 `openspec validate --specs --strict`

## 7. Paused accounts and the operator surface

- [x] 7.1 A paused Claude account stays eligible for warmup (sweep + trigger); the
      ChatGPT path keeps the active-only rule
- [x] 7.2 SwiftBar menu drives the restarts: per-account "Restart limit", "Restart ALL
      limits", the server-wide auto-restart toggle, and a per-account toggle
- [x] 7.3 Menu also exposes the per-account pace margin and pre-reset window so an
      account can be held back until its window is about to reset

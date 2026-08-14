# Tasks

## 1. The flow

- [x] 1.1 Add a `login` subcommand to `scripts/swiftbar/claudex-lb.1m.ts`:
      PKCE, authorize URL, browser open, pasted code, token exchange.
- [x] 1.2 Verify the returned state against the state the run started with, and
      refuse a code that carries no `#`.
- [x] 1.3 Read the email from the token response and the plan from
      `GET /api/oauth/profile`, treating a failed profile fetch as cosmetic.
- [x] 1.4 Import through `POST /api/accounts/import` in the `{email,
      claudeAiOauth}` shape `anthropic_import.py` parses, with `expiresAt` in
      milliseconds.

## 2. The menu

- [x] 2.1 Add **Add a Claude account…** to the Claude section only, with
      `terminal=true` — the flow has to show a URL and read a pasted code.
- [x] 2.2 Print `login` errors to the Terminal window instead of rendering menu
      lines or firing a notification.
- [x] 2.3 Document the subcommand in the plugin header and
      `scripts/swiftbar/README.md`.

## 3. Verify

- [x] 3.1 Menu renders the entry in the Claude section and not in the Codex one.
- [x] 3.2 `login` builds the authorize URL with Claude Code's client, scopes,
      and manual redirect, and opens it.
- [x] 3.3 A malformed code is refused with its reason rather than sent upstream.
- [ ] 3.4 Complete one real sign-in end to end and confirm the account lands in
      the pool with its own email and plan. Cannot be exercised without real
      credentials — the token exchange and profile fetch stay unproven until
      this runs.

## 4. Review findings

- [x] 4.1 `fail()` throws rather than exiting 0 for terminal subcommands. Five
      reachable paths ended in `process.exit(0)`, so a rotated dashboard password
      or a momentarily unreachable proxy dropped a freshly minted, single-use
      refresh token while printing SwiftBar menu syntax and reporting success.
- [x] 4.2 `cmdLogin` authenticates against the proxy before generating the PKCE
      challenge or opening the browser, so that class of failure costs a Terminal
      window rather than a completed sign-in.
- [x] 4.3 Verified both: an unreachable proxy exits 1 with the reason and opens
      no browser; the real configuration passes the preflight and reaches the
      code prompt.
- [x] 4.4 Document that completing the flow for an account already in the pool
      re-authorizes it and resets its runtime state — pre-existing behaviour of
      the import endpoint, newly one click away.

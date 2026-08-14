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

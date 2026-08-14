## Why

There is no way to add a Claude account to claudex-lb that does not start on
somebody's Mac. The dashboard's Add account button runs the ChatGPT flow, and
the server carries Anthropic token *refresh* only — no authorization-code flow
exists anywhere in it. Every Claude seat in the pool therefore arrives the same
way: `claude login` locally, then `push-account.ts` to hand the credential over.

That route works and has real costs. `claude login` overwrites this Mac's
keychain, so the account already sitting there is displaced — and if it had not
been pushed yet, its chain is simply gone, because Claude refresh tokens are
single-use and there is no second copy. The credential Claude Code writes also
carries no email, so `push-account` has to reconstruct the identity from
`~/.claude.json` and cross-check the two against each other; when they disagree
it can only refuse, because guessing would overwrite a healthy row on the proxy
under the wrong name. And the whole thing requires a Mac with Claude Code
installed, which the proxy's own host is not.

## What Changes

- The menu bar's Claude section gains **Add a Claude account…**, which runs
  Anthropic's authorization-code flow directly: PKCE challenge, the claude.ai
  authorize page, a pasted code, a token exchange, and an import into the pool.
- The account's email and plan come from the token exchange and the OAuth
  profile, so the account arrives under its own identity. No `~/.claude.json`
  lookup, no identity cross-check, and no synthetic `@imported.local` address
  that can never dedupe.
- Nothing local is touched: no keychain write, no `~/.claude.json`, no effect on
  whichever account Claude Code is logged into on this Mac. The flow can be run
  while signed in as somebody else, repeatedly, without displacing anything.
- The entry appears in the Claude section only. ChatGPT accounts are added
  through the dashboard's own flow, which is a different protocol with a
  different client; one button cannot serve both.
- `push-account.ts` stays. It is still the way to hand over an account that is
  *already* logged in on this Mac, which is a different job from adding a new
  one.

## Capabilities

### New Capabilities

None. This adds no server surface — it is a client of the existing
`POST /api/accounts/import`, the same endpoint `push-account.ts` uses.

### Modified Capabilities

None.

## Impact

- Menu bar: `scripts/swiftbar/claudex-lb.1m.ts` gains a `login` subcommand and
  one menu entry; `scripts/swiftbar/README.md` documents both.
- No server change, no schema change, no migration, no new endpoint. The
  credential is delivered in the shape `anthropic_import.py` already parses.
- Out of scope, and next: the same flow server-side, so the dashboard can add a
  Claude account with no Mac involved at all. This change is deliberately the
  smaller half — it proves the flow against Anthropic before it becomes an
  endpoint with a stored PKCE verifier and a callback to reconcile.

## Simplicity

No new setting and no new configuration: the flow reuses the dashboard base URL
and session the plugin already has. It adds one menu entry, in one section, that
does the thing the section is about. The alternative shape — a button that
shells out to `claude login` and then `push-account` — needs no new protocol
code but keeps every cost above, and makes the menu bar responsible for a
credential swap on the operator's own machine.

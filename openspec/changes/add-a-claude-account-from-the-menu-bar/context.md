# Context

## The flow, end to end

Anthropic's own client, run verbatim. The parameters are Claude Code's, which is
what makes the resulting token usable for inference rather than a Console key.

| Step | Where |
|---|---|
| PKCE | `verifier = base64url(random 32B)`, `challenge = base64url(sha256(verifier))`, `state = base64url(random 32B)` |
| Authorize | `https://claude.com/cai/oauth/authorize` — `code=true`, `client_id=9d1c250a-…`, `response_type=code`, `redirect_uri`, `scope`, `code_challenge`, `code_challenge_method=S256`, `state` |
| Redirect | `https://platform.claude.com/oauth/code/callback` — the paste-the-code page |
| Exchange | `POST https://platform.claude.com/v1/oauth/token` — `grant_type=authorization_code`, `code`, `redirect_uri`, `client_id`, `code_verifier`, `state` |
| Profile | `GET https://api.anthropic.com/api/oauth/profile`, bearer the new access token |
| Import | `POST /api/accounts/import` with `{email, claudeAiOauth}` |

Scopes are the full Claude Code set: `org:create_api_key user:profile
user:inference user:sessions:claude_code user:mcp_servers user:file_upload`.

The manual redirect is what makes this work without a callback listener. The
callback page renders the code as `authorizationCode#state` in one string, which
the plugin splits on `#` and checks against the state it started with.

## Why the redirect matters more than it looks

`redirect_uri` is part of the signed exchange: the value sent to `/token` must be
byte-identical to the one sent to `/authorize`, or the exchange fails. Using the
manual page for both is what lets this run with no listening socket — which is
also what will let the same code run server-side later, on a host with no
browser and no loopback the operator can reach.

## Why not `claude login` plus push-account

Both were considered. The shell-out is less code and no protocol work, and it
was rejected on what it does to the machine it runs on:

- `claude login` writes the new account over the keychain item. The displaced
  account is recoverable only if it was already pushed; nothing writes the
  per-account backups `push-account --from-backup` reads any more.
- The credential Claude Code stores carries no email. `push-account` recovers it
  from `oauthAccount.emailAddress` in `~/.claude.json` — a second file with a
  second writer — and refuses when the two disagree, because the failure mode is
  pushing one account's chain under another's name and overwriting a healthy row.
- It needs a Mac with Claude Code installed. The proxy host is not one.

The OAuth flow has none of those: the token response states the email, nothing
local is written, and the only local requirement is a browser.

## What is proven and what is not

The import leg is proven — it is the same endpoint and the same payload shape
that pushed a live account (`jjwild@gmx.de`, `claude_max`) into the pool on
2026-08-14, which then polled usage normally. URL construction, the state
mismatch check, and the malformed-code path are exercised. The token exchange and
profile fetch are unproven until someone completes a sign-in; they cannot be
exercised without real credentials.

## The exit-0 trap, and why the preflight comes first

SwiftBar's contract for a plugin is "print a menu and exit 0", and the plugin's
`fail()` implements exactly that. That contract is precisely wrong for this
subcommand: by the time it talks to the proxy it is holding a freshly minted,
single-use Anthropic refresh token that exists nowhere else. An exit 0 there
drops it *and reports success* — the operator sees SwiftBar menu syntax in a
Terminal window, and the account they just signed in for is simply gone.

A review pass counted **five** reachable `fail()` calls on that path, not the two
that were obvious: the missing-password branch, the unreachable-host branch in
`apiFetch`, and three inside the dashboard login itself — network error, a non-OK
login response, and a response carrying no session cookie. A merely *rotated*
dashboard password was enough to hit it.

Two changes, because either alone leaves a hole:

- `fail()` throws instead of exiting when the running subcommand is a terminal
  one. This covers all five paths and any added later, since it is the shared
  exit rather than each call site.
- `cmdLogin` makes an authenticated request **before** generating the PKCE
  challenge or opening the browser. A dead proxy or a rotated password is then
  discovered while nothing has been minted, so the failure costs a Terminal
  window rather than a sign-in.

The preflight also warms the session cookie the import will reuse, so the
authenticated call is not extra work.

## Re-authorizing an account that is already in the pool

The import matches an Anthropic account on `(provider, email)` and, when it
finds one, overwrites the tokens *and* the row's runtime state: status,
deactivation reason, `reset_at`, `blocked_at`, and the routing-unavailable mark.
So completing this flow while the browser is signed into a seat the pool already
holds will flip a rate-limited seat back to active with its reset time cleared,
and the selector will route to it while the upstream is still limiting.

This is pre-existing behaviour of `POST /api/accounts/import` — the dashboard's
own import UI and `push-account.ts` reach it the same way — so this change adds a
trigger, not a behaviour. It is called out here because the new entry makes that
trigger one click from a menu whose default browser session is very often
already signed into a pooled account, which is why the flow's own instructions
lead with the private-window advice.

## Failure modes handled

- **Pasted code without a `#`.** Refused with the reason, rather than sent to the
  exchange to come back as an opaque 400.
- **State mismatch.** Refused. A code from a different sign-in than the one this
  run started is not this operator's account.
- **Profile fetch fails.** Costs the plan label only — the email is already known
  from the token response, and the usage poller corrects the plan on its first
  read. It must not fail an import over a cosmetic field.
- **Errors during `login`.** Printed to the Terminal window rather than rendered
  as SwiftBar menu lines or flattened into a notification, both of which drop the
  detail that says which step failed.

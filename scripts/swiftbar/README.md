# SwiftBar plugin — Claude + Codex account switcher for claudex-lb

`claudex-lb.1m.ts` is a [SwiftBar](https://github.com/swiftbar/SwiftBar) menu-bar
plugin for claudex-lb with one section per provider — **Claude ✳ (anthropic)**
and **Codex ⇄ (openai)**, they are separate assistants and never affect each
other. Per section it shows which account the load balancer will serve the
**next** request from (5h/weekly windows, request counts, cost, last request)
and lets you pin any account manually or return to auto load-balancing.

It is a pure dashboard-API client: no server changes, no credential custody.
"Next" comes from `GET /api/accounts/next-up`, which runs the pool's own
selector as a dry run — it takes no lease and changes nothing. The newest
request log row used to answer this instead, which was wrong in exactly the
cases worth looking at: right after a pin, a pause, or a window running out it
went on naming the previous account until fresh traffic arrived, and on an idle
pool it never caught up.

The line reads **"Likely next"** when the configured routing strategy draws at
random among the accounts with capacity, so a coin flip is never shown as a
settled answer. A pin, a deterministic strategy, or a single candidate makes it
exact. If the server reports that nothing can serve, the menu says so rather
than guessing a name.

- **Pin an account**: writes `PUT /api/accounts/<id>/pin`, then reactivates the
  target if it was paused (in that order, so a failed pin leaves nothing
  half-applied). Other accounts stay live rather than being paused, so failover
  has somewhere to go. The pin is its own field: an account keeps its routing
  policy while pinned and returns to it when the pin lifts. Provider scoping is
  enforced client-side on each account's `provider` field — deployed servers may
  ignore the `?provider=` query param, so the plugin never relies on it.
- **Auto mode (per section)**: clears that provider's pin, drops any leftover
  `burn_first` mark, and reactivates its paused accounts.
- Menu bar title: `✳71% ⇄69%` — remaining window percent per provider's
  next account, `📌` when manually pinned.
- **Usage-based seats** (an enterprise seat billing against dollars rather than a
  rolling window) show the pool they can still spend from. A seat draws its plan
  allowance down first and only then the extra-usage pool behind it, so once the
  allowance is gone the badge follows the money — `58% left · $115.14` rather
  than the spent budget's `0% left · $0.00`. A pool that is switched off is never
  selected, whatever it reports. When every pool is spent the seat contributes no
  figure to the menu-bar title at all, and the title falls back to the least-used
  window in the pool: `100%` is a true statement about money nobody can spend,
  printed where the reader is asking how much room there is.

## Requirements

- [bun](https://bun.sh) (`~/.bun/bin`, Homebrew, or `/usr/local/bin`)
- SwiftBar
- A claudex-lb dashboard password

## Install

```bash
# 1. Config (base URL of your claudex-lb deployment)
mkdir -p ~/.config/claudex-lb
printf '{"baseUrl": "https://proxy.example.com"}' > ~/.config/claudex-lb/menubar.json
chmod 600 ~/.config/claudex-lb/menubar.json

# 2. Dashboard password → macOS Keychain (preferred; "password" in menubar.json also works)
security add-generic-password -s claudex-lb-dashboard -a menubar -w '<dashboard password>'

# 3. Symlink into SwiftBar's *configured* plugin folder — not necessarily the
#    default one. Check it first:
#      defaults read com.ameba.SwiftBar PluginDirectory
ln -sf "$(git rev-parse --show-toplevel)/scripts/swiftbar/claudex-lb.1m.ts" \
  "$(defaults read com.ameba.SwiftBar PluginDirectory)/"
```

The `1m` in the filename is the SwiftBar refresh interval. The plugin logs in
once and caches the session cookie (`~/.config/claudex-lb/menubar-session.cookie`,
mode 600); it only re-logins after a 401, so the dashboard login rate limit is
never in play. A provider with zero accounts simply renders no section.

Use HTTPS for every remote deployment. The menu sends the dashboard credential
to `baseUrl`; plain HTTP is appropriate only for a loopback address such as
`http://127.0.0.1:2455`.

## Adding a Claude account

**Add a Claude account…** in the Claude section opens a Terminal window and runs
Anthropic's own authorization-code flow: it prints and opens the claude.ai
sign-in URL, you paste back the code the callback page gives you, and the
resulting credential is imported into the pool.

Nothing on this Mac is touched — no keychain write, no `~/.claude.json`, and no
effect on whichever account Claude Code is logged into here. Sign in from a
private window to add an account other than the one the browser already holds,
and run it as often as you like.

The account arrives under its own identity: the email comes from the token
exchange and the plan from the OAuth profile, so there is no `~/.claude.json`
lookup and no synthetic `@imported.local` address. That is the difference from
`scripts/push-account/push-account.ts`, which is still the right tool for handing
over an account **already** logged in on this Mac, and which has to reconstruct
the identity because the credential Claude Code stores carries no email.

The entry is Claude-only. ChatGPT accounts are added through the dashboard's own
flow — a different protocol with a different client.

## Subcommands

The menu invokes the plugin itself: `claudex-lb.1m.ts switch <account_id>`,
`claudex-lb.1m.ts auto [openai|anthropic]`, and `claudex-lb.1m.ts login`.
Errors from menu actions surface as macOS notifications; `login` runs in a
Terminal window and prints its errors there instead, since a notification would
drop the detail that says which step failed.

## Embedding in another menu-bar plugin

`menu-blocks` and `claude-menu` print the same data for a host plugin to embed
(`#BEGIN:`-separated blocks and one standalone block respectively); both exit
non-zero without output when the server is unreachable, so the host can fall
back. Both cover **Claude and Codex**: `claude-menu` appends the Codex section
below the Claude one, and `menu-blocks` puts the Codex accounts at the end of
its `accounts` block rather than behind a new `#BEGIN:` marker — a host splits
on the markers it knows, so a new one would be dropped silently.

Codex accounts get the same click-to-serve switching and the same pace /
pre-reset controls as Claude ones. The 5h-window restart entries stay
Claude-only. `#TITLE:` is unchanged (still the Claude figure) so the host's
menu-bar text keeps its current shape.

# SwiftBar plugin — Claude + Codex account switcher for claudex-lb

`claudex-lb.1m.ts` is a [SwiftBar](https://github.com/swiftbar/SwiftBar) menu-bar
plugin for claudex-lb with one section per provider — **Claude ✳ (anthropic)**
and **Codex ⇄ (openai)**, they are separate assistants and never affect each
other. Per section it shows which account the load balancer is currently
serving (5h/weekly windows, request counts, cost, last request) and lets you
pin any account manually or return to auto load-balancing.

It is a pure dashboard-API client: no server changes, no credential custody.
"Current" is the account of the most recent proxied request per provider (a
proxy for "live", not ground truth while several accounts are active).

- **Pin an account**: reactivates the target first, then pauses every other
  pausable account **of the same provider** (the pool is never empty; a failed
  target-reactivate aborts before anything is paused). Provider scoping is
  enforced client-side on each account's `provider` field — deployed servers
  may ignore the `?provider=` query param, so the plugin never relies on it.
- **Auto mode (per section)**: reactivates that provider's paused accounts.
- Menu bar title: `✳71% ⇄69%` — remaining window percent per provider's
  current account, `📌` when manually pinned.

## Requirements

- [bun](https://bun.sh) (`~/.bun/bin`, Homebrew, or `/usr/local/bin`)
- SwiftBar
- A claudex-lb dashboard password

## Install

```bash
# 1. Config (base URL of your claudex-lb deployment)
mkdir -p ~/.config/claudex-lb
printf '{"baseUrl": "https://codex-proxy.aiwerke.de"}' > ~/.config/claudex-lb/menubar.json
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

## Subcommands

The menu invokes the plugin itself: `claudex-lb.1m.ts switch <account_id>` and
`claudex-lb.1m.ts auto [openai|anthropic]`. Errors from menu actions surface
as macOS notifications.

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

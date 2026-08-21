# claudex-lb

claudex-lb is a community fork of
[Soju06/codex-lb](https://github.com/Soju06/codex-lb). It retains
Codex/ChatGPT account pooling and adds native Anthropic OAuth and API-key
account pooling for Claude Code.

| Client path | Pooled upstream accounts |
|---|---|
| `Claude Code → /v1/messages` | Anthropic/Claude only |
| `Codex → Responses API` | ChatGPT/Codex only |

Claude requests stay on the native Anthropic Messages protocol. They are not
translated through LiteLLM and are never routed to non-Claude models.

| ![dashboard](screenshots/dashboard.jpg) | ![accounts](screenshots/accounts.jpg) |
|:---:|:---:|

## Features

- **Claude + Codex pooling** — isolated account selection and failover per provider
- **Native Claude relay** — direct Messages API and byte-preserving SSE
- **Usage tracking** — per-account windows, spend pools, tokens, cost, and trends
- **API keys** — per-key rate limits by token, cost, window, model
- **Dashboard auth** — password + optional TOTP
- **OpenAI-compatible** — Codex CLI, OpenCode, any OpenAI client
- **Auto model sync** — available models fetched from upstream
- **SwiftBar menu** — macOS quota status, next-serving account, pins, and routing controls

## Where to go

- [Getting Started](getting-started.md) — build this fork from source and bootstrap it
- [Client Setup](client-setup.md) — Claude Code, Codex CLI, OpenCode, OpenClaw, and SDKs
- [Configuration](configuration.md) — the few settings that matter
- [Authentication](authentication.md) — dashboard auth modes
- [API Keys](api-keys.md) — protecting proxy routes
- [Routing](routing.md) — routing strategy guide
- [Pace Gates](pace-gates.md) — bounding how fast a shared account is drawn from
- [Account Pin](account-pin.md) — routing everything to one account until it cannot serve
- [Claude Statistics](claude-statistics.md) — how Claude traffic appears in the request log
- [SwiftBar menu](https://github.com/joschi655/claudex-lb/tree/main/scripts/swiftbar) — macOS pool status and controls
- [Database](database.md) — SQLite / PostgreSQL, data paths, Postgres upgrades
- [Deployment](deployment/docker.md) — Docker, [Kubernetes](deployment/kubernetes.md), [remote access](deployment/remote.md)
- [Troubleshooting](troubleshooting.md)

## Screenshots

| Settings | Login |
|:---:|:---:|
| ![settings](screenshots/settings.jpg) | ![login](screenshots/login.jpg) |

| Dashboard (dark) | Accounts (dark) | Settings (dark) |
|:---:|:---:|:---:|
| ![dashboard-dark](screenshots/dashboard-dark.jpg) | ![accounts-dark](screenshots/accounts-dark.jpg) | ![settings-dark](screenshots/settings-dark.jpg) |

---

claudex-lb is spec-driven: normative behavior lives in
[OpenSpec capabilities](https://github.com/joschi655/claudex-lb/tree/main/openspec/specs)
in the repository. Docs pages describe how to use the project and link back to
the specs that govern them.

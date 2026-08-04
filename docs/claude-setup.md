# Claude Setup

codex-lb supports Claude through commercial Anthropic Console API keys. It does
not support signing in to Claude.ai Free, Pro, or Max accounts, importing their
OAuth tokens, or pooling consumer subscriptions. Use this API-key path for a
provider-supported integration; operating codex-lb does not replace your own
review of Anthropic's terms and organization policies.

## Add an Anthropic account

1. Create an API key in the [Anthropic Console](https://console.anthropic.com/settings/keys).
2. Open **Accounts** in codex-lb and select **Claude**.
3. Select **Add account** then **Claude API key**.
4. Enter a label and the Console API key.

The key is encrypted at rest and is never shown again by codex-lb. Use
**Replace API key** on the account if Anthropic rotates or revokes it.

## Create a client key

Enable API-key authentication under **Settings**, then create a codex-lb key
under **APIs**. Assign that client key to the Claude accounts it may use and,
if needed, restrict its model allowlist or request budget. Account assignments
are hard boundaries: a request cannot fall back to an unassigned account, and
Claude traffic never selects an OpenAI account.

Claude request cost is intentionally unpriced. A `cost_usd` limit that applies
to the requested Claude model therefore rejects the request before it reaches
Anthropic; use request or token limits until an explicit Anthropic pricing
source is available. Cost limits filtered to unrelated models do not block
Claude traffic.

## Configure Claude Code

Point Claude Code at the codex-lb origin and provide the codex-lb client key,
not the upstream Anthropic Console key:

```bash
export ANTHROPIC_BASE_URL="https://codex-lb.example"
export ANTHROPIC_AUTH_TOKEN="sk-clb-..."
claude
```

For a local instance, use `http://127.0.0.1:2455` as the base URL. Claude Code
sends standard requests to `/v1/messages` and `/v1/messages/count_tokens`;
codex-lb authenticates the client key, chooses an eligible Claude account, and
replaces the client credential before forwarding upstream.

Do not run Claude Code's native Claude.ai login flow for this setup. Native
consumer login credentials are neither required nor accepted by codex-lb.

## Verify traffic and capacity

Run a Claude Code request, then open the dashboard:

- **All** combines request, token, error, and latency statistics across OpenAI
  and Claude.
- **Claude** shows only Anthropic traffic and account-level API rate-limit
  snapshots.
- OpenAI credits and Claude rate limits stay separate because they are not
  compatible capacity units.
- A combined cost is marked partial when Claude requests have no configured
  price instead of treating them as zero-cost traffic.

An Anthropic `401` means the Console API key must be replaced. A `429` records
the upstream reset metadata and may fail over to another eligible assigned
Claude account before any response bytes are sent.

---

*Spec: [anthropic-provider](https://github.com/Soju06/codex-lb/tree/main/openspec/specs/anthropic-provider)*

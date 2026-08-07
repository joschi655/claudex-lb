import type { AccountSummary } from "@/features/accounts/schemas";

/**
 * The account ids currently carrying traffic, one per provider.
 *
 * "Serving" is a question about traffic, so it is answered from the request
 * log's most recent entry rather than from routing policy — a pinned or
 * burn-first account can be marked and still be serving nothing, which is
 * exactly the case a policy badge hides. The server only reports activity
 * inside a recent window, so an idle pool yields an empty set rather than
 * naming whoever went last.
 *
 * Scoped per provider because Claude and Codex traffic are independent: each
 * has its own serving account, and the newest row overall would let the busier
 * provider speak for both.
 */
export function servingAccountIds(accounts: AccountSummary[]): Set<string> {
  const newestByProvider = new Map<string, { id: string; at: number }>();
  for (const account of accounts) {
    if (!account.lastServedAt) continue;
    const at = Date.parse(account.lastServedAt);
    if (Number.isNaN(at)) continue;
    const provider = account.provider ?? "unknown";
    const current = newestByProvider.get(provider);
    if (!current || at > current.at) {
      newestByProvider.set(provider, { id: account.accountId, at });
    }
  }
  return new Set([...newestByProvider.values()].map((entry) => entry.id));
}

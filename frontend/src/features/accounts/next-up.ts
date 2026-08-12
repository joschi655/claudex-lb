import type { NextAccountsResponse } from "@/features/accounts/schemas";

/** Whether the account named as next is a settled answer or a front-runner. */
export type NextUpMark = { certain: boolean };

/**
 * The account ids each provider would route the *next* request to.
 *
 * "Serving" used to be answered from the newest request log row, which reports
 * where traffic went rather than where it is going. Those diverge exactly when
 * an operator is looking: the moment an account is pinned, paused, rate
 * limited, or crosses a pace gate, the log keeps naming it until new traffic
 * arrives — and on an idle pool, indefinitely. So the answer comes from the
 * pool's own dry-run selection instead.
 *
 * Entries that name no account are dropped rather than rendered: a provider
 * with nothing eligible has nothing to mark, and its accounts show their status
 * as usual.
 */
export function nextUpMarks(
  response: NextAccountsResponse | undefined,
): Map<string, NextUpMark> {
  const marks = new Map<string, NextUpMark>();
  for (const entry of response?.nextUp ?? []) {
    if (!entry.accountId) continue;
    // A provider already listed wins on first mention; the endpoint reports one
    // entry per provider, so a duplicate id would be the same answer twice.
    if (marks.has(entry.accountId)) continue;
    marks.set(entry.accountId, { certain: entry.certain });
  }
  return marks;
}

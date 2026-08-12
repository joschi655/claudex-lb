import type { AccountSummary } from "@/features/accounts/schemas";

/** What an account actually presents, after the setting has had its say. */
export type ResolvedQuotaKind = "subscription" | "usage_based";

/**
 * Which quota surface to show for an account.
 *
 * Both the compact list row and the detail panel call this rather than each
 * deciding for itself — they disagreed once already, which is how a budget seat
 * ended up rendering its budget in one place and nothing at all in the other.
 *
 * `auto` keeps the original inference: a dollar budget and no rolling window
 * means usage-based, anything else means subscription. An explicit kind wins
 * outright, including when the data it wants is missing — falling back there
 * would show window bars on an account the operator has declared usage-based,
 * which is the exact state they set the field to correct.
 */
export function resolveQuotaKind(account: AccountSummary): ResolvedQuotaKind {
  if (account.quotaKind === "usage_based") return "usage_based";
  if (account.quotaKind === "subscription") return "subscription";

  // Deliberately the remaining percentages only, which is the test the detail
  // panel already applied. A stale `resetAt` or `windowMinutes` is not evidence
  // of a live window -- a seat that moved to usage-based billing keeps those
  // long after it stops reporting usage against them, and counting them would
  // hold such a seat on the window presentation forever. That is one of the
  // cases the explicit setting exists for, but `auto` must not regress it.
  const hasWindow =
    account.usage?.primaryRemainingPercent != null ||
    account.usage?.secondaryRemainingPercent != null ||
    account.usage?.monthlyRemainingPercent != null;

  return account.spendBudget != null && !hasWindow ? "usage_based" : "subscription";
}

import type {
  AccountExtraCredits,
  AccountSpendBudget,
  AccountSummary,
} from "@/features/accounts/schemas";

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

/** Which of a usage-based account's two dollar pools is being drawn down. */
export type LiveQuotaPoolKind = "budget" | "extra_credits";

export type LiveQuotaPool = {
  kind: LiveQuotaPoolKind;
  /** Names the pool, so a plan budget is never mistaken for the top-up behind it. */
  label: string;
  /**
   * Clamped to [0, 100]; an over-limit pool reads 0 rather than negative.
   *
   * `null` when the pool reports no limit, because then there is no ratio to
   * take. The poller stores `used_percent = 0` in that case -- "no limit set, so
   * no meaningful ratio" -- and reading that as "nothing spent" would paint a
   * full bar over a pool whose state is simply unknown.
   */
  remainingPercent: number | null;
  remaining: number | null;
  limit: number | null;
  currency: string | null;
  resetAt: string | null;
  /** No headroom left. The seat cannot spend from this pool, or from any other. */
  spent: boolean;
  /** The pool reports a limit, so its percentage means something. */
  measurable: boolean;
};

/**
 * The dollar pool a usage-based account can still spend from.
 *
 * A seat draws its plan allowance down first and only then the extra-usage pool
 * behind it, so "live" is the first of the two with headroom -- not the larger
 * one and not the one with the most left. Reading only the first of the two is
 * how a seat at $1000 of $1000 came to render `0% left · $0.00` while $115 of
 * its top-up sat unspent and it was a candidate for the next request.
 *
 * `enabled` is load-bearing on the top-up pool. It is reported even when
 * switched off -- deliberately, since that is a state an operator acts on -- and
 * a disabled pool still carries a limit and a remainder. Selecting it would
 * claim headroom on a seat that has none.
 *
 * Returns `null` when the account reports no pool at all, which is a usage-based
 * account polled before its first budget read; callers say so rather than
 * reverting to window bars.
 */
export function resolveLiveQuotaPool(account: AccountSummary): LiveQuotaPool | null {
  const budget = toPool(account.spendBudget);
  // Disabled pools are dropped here rather than ranked below the budget: they
  // are not a fallback, they are money that cannot be spent.
  const extra = account.extraCredits?.enabled === true ? toExtraPool(account.extraCredits) : null;

  // Headroom requires a limit to have headroom *in*. A pool without one is not
  // a candidate: it cannot be shown to have room, and it cannot be shown to be
  // out either.
  if (budget != null && budget.measurable && !budget.spent) return budget;
  if (extra != null && extra.measurable && !extra.spent) return extra;

  // Nothing measurable has room. An unmeasurable pool is the honest answer
  // before a spent one: "this seat's remaining budget is 0" is a claim, and the
  // pool that would cover the overflow has not said whether it can.
  const unmeasurable = [extra, budget].find((p) => p != null && !p.measurable);
  if (unmeasurable != null) return unmeasurable;

  // Genuinely out. Prefer the top-up pool when the account has one: it is the
  // pool the upstream names when a spent seat refuses a request.
  return extra ?? budget;
}

// The plan budget's utilization is always a real figure: the poller only
// recognizes a dollar bucket that states a limit, and carries the utilization
// the payload itself reported. So a budget is always measurable, even in the
// shapes where the limit did not survive into the row.
function toPool(budget: AccountSpendBudget | null | undefined): LiveQuotaPool | null {
  if (budget == null) return null;
  return {
    kind: "budget",
    label: "Budget",
    remainingPercent: remainingPercentOf(budget.usedPercent),
    remaining: budget.remaining ?? null,
    limit: budget.limit ?? null,
    currency: budget.currency ?? null,
    resetAt: budget.resetAt ?? null,
    spent: budget.usedPercent >= 100,
    measurable: true,
  };
}

// The top-up pool is the asymmetric one. Its utilization is derived from limit
// and used, and the poller writes 0 when either is missing -- "no limit set, so
// no meaningful ratio" -- which is indistinguishable from a genuinely untouched
// pool unless the limit is checked.
function toExtraPool(credits: AccountExtraCredits): LiveQuotaPool {
  const measurable = credits.limit != null;
  return {
    kind: "extra_credits",
    // "Extra usage", matching the detail panel and the wording Anthropic itself
    // uses when a seat runs out of it. Two names for one pool on two views of
    // the same account is the confusion this whole resolver exists to avoid.
    label: "Extra usage",
    remainingPercent: measurable ? remainingPercentOf(credits.usedPercent) : null,
    remaining: credits.remaining ?? null,
    limit: credits.limit ?? null,
    currency: credits.currency ?? null,
    // The top-up pool rides the plan's period rather than resetting on its own,
    // so it reports no reset of its own to show.
    resetAt: null,
    spent: measurable && credits.usedPercent >= 100,
    measurable,
  };
}

function remainingPercentOf(usedPercent: number): number {
  return Math.max(0, Math.min(100, 100 - usedPercent));
}

/**
 * One pool amount, in the pool's own currency.
 *
 * Shared rather than reimplemented per surface for the same reason the resolver
 * is: a pool rendered as `$115.14` on one screen and `115.14` on another is the
 * same disagreement in a smaller place.
 */
export function formatQuotaPoolAmount(
  amount: number | null | undefined,
  currency: string | null | undefined,
): string | null {
  if (amount == null || !Number.isFinite(amount)) return null;
  return new Intl.NumberFormat(undefined, {
    style: "currency",
    currency: currency ?? "USD",
    maximumFractionDigits: 2,
  }).format(amount);
}

/** The "$115.14 of $200 left" line, or the best of it the pool can support. */
export function formatQuotaPoolAmounts(pool: LiveQuotaPool): string | null {
  const remaining = formatQuotaPoolAmount(pool.remaining, pool.currency);
  const limit = formatQuotaPoolAmount(pool.limit, pool.currency);
  if (remaining && limit) return `${remaining} of ${limit} left`;
  if (remaining) return `${remaining} left`;
  return null;
}

/**
 * The footnote under a pool's bar: amounts when it has them, and otherwise the
 * reason there is no figure. Shared so all three compact surfaces say the same
 * thing about the same pool.
 */
export function describeQuotaPool(pool: LiveQuotaPool | null): string {
  if (pool == null) return "No budget reported yet";
  const amounts = formatQuotaPoolAmounts(pool);
  if (amounts) return amounts;
  // An enabled pool with no limit is unlimited or not yet granted; either way
  // the poller has no ratio to store and says so rather than implying a full one.
  if (!pool.measurable) return "No limit reported";
  if (pool.spent) return "Nothing left to spend";
  return "";
}

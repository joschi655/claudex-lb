import { describe, expect, it } from "vitest";

import { resolveLiveQuotaPool, resolveQuotaKind } from "@/features/accounts/quota-kind";
import { createAccountSummary } from "@/test/mocks/factories";

const WINDOWLESS = {
  usage: {
    primaryRemainingPercent: null,
    secondaryRemainingPercent: null,
    monthlyRemainingPercent: null,
  },
  resetAtPrimary: null,
  resetAtSecondary: null,
  resetAtMonthly: null,
  windowMinutesPrimary: null,
  windowMinutesSecondary: null,
  windowMinutesMonthly: null,
} as const;

const BUDGET = {
  usedPercent: 84,
  used: 840,
  limit: 1000,
  remaining: 160,
  currency: "USD",
  resetAt: null,
} as const;

describe("resolveQuotaKind", () => {
  it("infers usage-based from a budget with no window", () => {
    const account = createAccountSummary({ ...WINDOWLESS, spendBudget: BUDGET });

    expect(resolveQuotaKind(account)).toBe("usage_based");
  });

  it("infers subscription from windows", () => {
    expect(resolveQuotaKind(createAccountSummary())).toBe("subscription");
  });

  it("infers subscription when an account reports both", () => {
    // Ambiguous data resolves the way it always has; the setting exists to
    // override it, not to have the inference guess differently.
    const account = createAccountSummary({ spendBudget: BUDGET });

    expect(resolveQuotaKind(account)).toBe("subscription");
  });

  it("lets an explicit usage_based win over reported windows", () => {
    const account = createAccountSummary({ quotaKind: "usage_based" });

    expect(resolveQuotaKind(account)).toBe("usage_based");
  });

  it("lets an explicit subscription win over a budget", () => {
    const account = createAccountSummary({
      ...WINDOWLESS,
      spendBudget: BUDGET,
      quotaKind: "subscription",
    });

    expect(resolveQuotaKind(account)).toBe("subscription");
  });

  it("keeps an explicit usage_based even with no budget to show", () => {
    // Falling back here would put window bars on an account the operator
    // declared usage-based -- the exact state they set the field to correct,
    // and indistinguishable from the setting having failed to save.
    const account = createAccountSummary({ ...WINDOWLESS, quotaKind: "usage_based" });

    expect(resolveQuotaKind(account)).toBe("usage_based");
  });

  it("ignores stale window metadata left behind by a seat that moved to billing", () => {
    // The factory supplies resetAtPrimary/windowMinutesPrimary by default. A
    // seat that switched to usage-based billing keeps those long after it stops
    // reporting usage against them, so counting them as a live window would
    // hold it on the subscription presentation forever.
    const account = createAccountSummary({
      usage: { primaryRemainingPercent: null, secondaryRemainingPercent: null },
      spendBudget: BUDGET,
    });
    expect(account.resetAtPrimary).not.toBeNull();
    expect(account.windowMinutesPrimary).not.toBeNull();

    expect(resolveQuotaKind(account)).toBe("usage_based");
  });

  it("treats a missing kind as auto", () => {
    const account = createAccountSummary({ ...WINDOWLESS, spendBudget: BUDGET });
    expect(account.quotaKind).toBeUndefined();

    expect(resolveQuotaKind(account)).toBe("usage_based");
  });
});

// Mirrors the live enterprise seat that motivated the resolver: the plan
// allowance fully spent, and the top-up pool behind it part-used with money
// left. Reading only the budget reports that seat as spent while it is still a
// candidate for the next request.
const SPENT_BUDGET = {
  usedPercent: 100,
  used: 1000,
  limit: 1000,
  remaining: 0,
  currency: "USD",
  resetAt: "2026-09-30T20:47:10Z",
} as const;

const LIVE_EXTRA_CREDITS = {
  enabled: true,
  usedPercent: 42.43,
  used: 84.86,
  limit: 200,
  remaining: 115.14,
  currency: "USD",
} as const;

describe("resolveLiveQuotaPool", () => {
  it("hands off to the extra-usage pool when the budget is spent", () => {
    const account = createAccountSummary({
      ...WINDOWLESS,
      quotaKind: "usage_based",
      spendBudget: SPENT_BUDGET,
      extraCredits: LIVE_EXTRA_CREDITS,
    });

    const pool = resolveLiveQuotaPool(account);

    expect(pool).toMatchObject({
      kind: "extra_credits",
      label: "Extra usage",
      remaining: 115.14,
      limit: 200,
      spent: false,
    });
    expect(pool?.remainingPercent).toBeCloseTo(57.57);
  });

  it("keeps the budget while it still has headroom", () => {
    const account = createAccountSummary({
      ...WINDOWLESS,
      quotaKind: "usage_based",
      spendBudget: BUDGET,
      extraCredits: LIVE_EXTRA_CREDITS,
    });

    expect(resolveLiveQuotaPool(account)).toMatchObject({
      kind: "budget",
      remainingPercent: 16,
      spent: false,
    });
  });

  it("never selects a disabled pool", () => {
    // Reported even when switched off, and still carrying a limit and a
    // remainder -- which is money the seat cannot spend.
    const account = createAccountSummary({
      ...WINDOWLESS,
      quotaKind: "usage_based",
      spendBudget: SPENT_BUDGET,
      extraCredits: { ...LIVE_EXTRA_CREDITS, enabled: false },
    });

    expect(resolveLiveQuotaPool(account)).toMatchObject({
      kind: "budget",
      remainingPercent: 0,
      spent: true,
    });
  });

  it("reports spent when neither pool has headroom", () => {
    const account = createAccountSummary({
      ...WINDOWLESS,
      quotaKind: "usage_based",
      spendBudget: SPENT_BUDGET,
      extraCredits: { ...LIVE_EXTRA_CREDITS, usedPercent: 100, used: 200, remaining: 0 },
    });

    expect(resolveLiveQuotaPool(account)).toMatchObject({
      kind: "extra_credits",
      remainingPercent: 0,
      spent: true,
    });
  });

  it("clamps an over-limit pool to zero rather than negative", () => {
    const account = createAccountSummary({
      ...WINDOWLESS,
      quotaKind: "usage_based",
      spendBudget: { ...SPENT_BUDGET, usedPercent: 118, used: 1180, remaining: -180 },
    });

    expect(resolveLiveQuotaPool(account)).toMatchObject({
      remainingPercent: 0,
      spent: true,
    });
  });

  it("falls back to the percentage when a pool reports no amounts", () => {
    const account = createAccountSummary({
      ...WINDOWLESS,
      quotaKind: "usage_based",
      spendBudget: { usedPercent: 30, used: null, limit: null, remaining: null, currency: null, resetAt: null },
    });

    expect(resolveLiveQuotaPool(account)).toMatchObject({
      kind: "budget",
      remainingPercent: 70,
      remaining: null,
      limit: null,
    });
  });

  it("returns nothing for an account that has reported no pool", () => {
    const account = createAccountSummary({ ...WINDOWLESS, quotaKind: "usage_based" });

    expect(resolveLiveQuotaPool(account)).toBeNull();
  });
});

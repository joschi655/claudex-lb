import { describe, expect, it } from "vitest";

import { resolveQuotaKind } from "@/features/accounts/quota-kind";
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

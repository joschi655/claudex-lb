import { act, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import { AccountCard } from "@/features/dashboard/components/account-card";
import { usePrivacyStore } from "@/hooks/use-privacy";
import { createAccountSummary } from "@/test/mocks/factories";

afterEach(() => {
  act(() => {
    usePrivacyStore.setState({ blurred: false });
  });
});

// The live enterprise seat this branch was written for: plan allowance spent,
// top-up pool behind it still holding money.
const USAGE_BASED_SEAT = {
  planType: "claude_enterprise",
  quotaKind: "usage_based",
  usage: {
    primaryRemainingPercent: null,
    secondaryRemainingPercent: null,
    monthlyRemainingPercent: null,
  },
  windowMinutesPrimary: null,
  windowMinutesSecondary: null,
  windowMinutesMonthly: null,
  resetAtPrimary: null,
  resetAtSecondary: null,
  spendBudget: {
    usedPercent: 100,
    used: 1000,
    limit: 1000,
    remaining: 0,
    currency: "USD",
    resetAt: "2026-09-30T20:47:10Z",
  },
  extraCredits: {
    enabled: true,
    usedPercent: 42.43,
    used: 84.86,
    limit: 200,
    remaining: 115.14,
    currency: "USD",
  },
} as const;

describe("AccountCard", () => {
  it.each([
    { label: "5h", primaryCeiling: 90, secondaryCeiling: null },
    { label: "Weekly", primaryCeiling: null, secondaryCeiling: 90 },
  ])("marks only the configured $label ceiling", ({ label, primaryCeiling, secondaryCeiling }) => {
    const account = createAccountSummary({
      usageCeilingPrimaryPct: primaryCeiling,
      usageCeilingSecondaryPct: secondaryCeiling,
    });

    render(<AccountCard account={account} />);

    expect(screen.getAllByTestId("usage-ceiling-marker")).toHaveLength(1);
    expect(screen.getByTestId("usage-ceiling-marker")).toHaveAttribute("title", `${label} ceiling at 90% used`);
  });

  it("marks both remaining bars at 10% for 90% used ceilings", () => {
    const account = createAccountSummary({
      usageCeilingPrimaryPct: 90,
      usageCeilingSecondaryPct: 90,
    });

    render(<AccountCard account={account} />);

    const markers = screen.getAllByTestId("usage-ceiling-marker");
    expect(markers).toHaveLength(2);
    expect(markers[0]).toHaveAttribute("title", "5h ceiling at 90% used");
    expect(markers[1]).toHaveAttribute("title", "Weekly ceiling at 90% used");
    for (const marker of markers) {
      expect(marker).toHaveStyle({ left: "10%" });
      expect(marker.parentElement).toHaveClass("relative");
      expect(marker.parentElement).not.toHaveClass("overflow-hidden");
    }
  });

  it.each([null, undefined])("omits ceiling markers and badges with %s ceilings", (ceilingPct) => {
    const account = createAccountSummary({
      usageCeilingPrimaryPct: ceilingPct,
      usageCeilingSecondaryPct: ceilingPct,
      usage: { primaryRemainingPercent: 5, secondaryRemainingPercent: 5 },
    });

    render(<AccountCard account={account} />);

    expect(screen.queryByTestId("usage-ceiling-marker")).not.toBeInTheDocument();
    expect(screen.queryByText("At ceiling")).not.toBeInTheDocument();
  });

  it.each([
    { label: "5h", primary: 5, secondary: 50 },
    { label: "Weekly", primary: 50, secondary: 5 },
  ])("shows the $label ceiling badge independently, including when pinned", ({ label, primary, secondary }) => {
    const account = createAccountSummary({
      pinned: true,
      usageCeilingPrimaryPct: 90,
      usageCeilingSecondaryPct: 90,
      usage: { primaryRemainingPercent: primary, secondaryRemainingPercent: secondary },
      resetAtPrimary: "2099-01-01T00:00:00Z",
      resetAtSecondary: "2099-01-01T00:00:00Z",
    });

    render(<AccountCard account={account} />);

    expect(screen.getAllByText("At ceiling")).toHaveLength(1);
    expect(screen.getByText("At ceiling")).toHaveAttribute(
      "title",
      `${label} usage reached this account's 90% ceiling. It is skipped until the window resets.`,
    );
  });

  it.each([50, null])("keeps markers but omits badges with %s remaining", (remainingPercent) => {
    const account = createAccountSummary({
      usageCeilingPrimaryPct: 90,
      usageCeilingSecondaryPct: 90,
      usage: { primaryRemainingPercent: remainingPercent, secondaryRemainingPercent: remainingPercent },
      resetAtPrimary: "2099-01-01T00:00:00Z",
      resetAtSecondary: "2099-01-01T00:00:00Z",
    });

    render(<AccountCard account={account} />);

    expect(screen.getAllByTestId("usage-ceiling-marker")).toHaveLength(2);
    expect(screen.queryByText("At ceiling")).not.toBeInTheDocument();
  });

  it("omits badges for stale samples after both windows reset", () => {
    const account = createAccountSummary({
      usageCeilingPrimaryPct: 90,
      usageCeilingSecondaryPct: 90,
      usage: { primaryRemainingPercent: 5, secondaryRemainingPercent: 5 },
      resetAtPrimary: "2025-01-01T00:00:00Z",
      resetAtSecondary: "2025-01-01T00:00:00Z",
    });

    render(<AccountCard account={account} />);

    expect(screen.getAllByTestId("usage-ceiling-marker")).toHaveLength(2);
    expect(screen.queryByText("At ceiling")).not.toBeInTheDocument();
  });
  it("renders both 5h and weekly quota bars for regular accounts", () => {
    const account = createAccountSummary();
    render(<AccountCard account={account} />);

    expect(screen.getByText("Plus")).toBeInTheDocument();
    expect(screen.getByText("5h")).toBeInTheDocument();
    expect(screen.getByText("Weekly")).toBeInTheDocument();
  });

  it("hides 5h quota bar for weekly-only accounts", () => {
    const account = createAccountSummary({
      planType: "free",
      usage: {
        primaryRemainingPercent: null,
        secondaryRemainingPercent: 76,
      },
      windowMinutesPrimary: null,
      windowMinutesSecondary: 10_080,
    });

    render(<AccountCard account={account} />);

    expect(screen.getByText("Free")).toBeInTheDocument();
    expect(screen.queryByText("5h")).not.toBeInTheDocument();
    expect(screen.getByText("Weekly")).toBeInTheDocument();
  });

  it("shows Monthly only for monthly-only free accounts", () => {
    const account = createAccountSummary({
      usageCeilingPrimaryPct: 90,
      usageCeilingSecondaryPct: 90,
      planType: "free",
      usage: {
        primaryRemainingPercent: null,
        secondaryRemainingPercent: null,
        monthlyRemainingPercent: 76,
      },
      windowMinutesPrimary: null,
      windowMinutesSecondary: null,
      windowMinutesMonthly: 43_200,
      resetAtPrimary: null,
      resetAtSecondary: null,
      resetAtMonthly: "2026-01-31T00:00:00.000Z",
    });

    render(<AccountCard account={account} />);

    expect(screen.getByText("Monthly")).toBeInTheDocument();
    expect(screen.queryByTestId("usage-ceiling-marker")).not.toBeInTheDocument();
    expect(screen.queryByText("At ceiling")).not.toBeInTheDocument();
    expect(screen.queryByText("5h")).not.toBeInTheDocument();
    expect(screen.queryByText("Weekly")).not.toBeInTheDocument();
  });

  it("labels staggered idle warm-up attempts as 5h", () => {
    const attemptedAt = new Date("2026-06-03T12:00:00Z").toISOString();
    const account = createAccountSummary({
      limitWarmupEnabled: true,
      limitWarmup: {
        window: "primary_idle",
        resetAt: 18_000,
        status: "succeeded",
        model: "gpt-5.1-codex-mini",
        attemptedAt,
        completedAt: attemptedAt,
        errorCode: null,
        errorMessage: null,
      },
    });

    render(<AccountCard account={account} />);

    expect(
      screen.getByText((text) => text.includes("Succeeded | 5h | Gpt-5.1-codex-mini")),
    ).toBeInTheDocument();
  });

  it("blurs the dashboard card title when privacy mode is enabled", () => {
    act(() => {
      usePrivacyStore.setState({ blurred: true });
    });
    const account = createAccountSummary({
      displayName: "AWS Account MSP",
      email: "aws-account@example.com",
    });

    const { container } = render(<AccountCard account={account} />);

    expect(screen.getByText("AWS Account MSP")).toBeInTheDocument();
    expect(container.querySelector(".privacy-blur")).not.toBeNull();
  });

  it("renders the credits row", () => {
    const account = createAccountSummary({
      creditsBalance: 959,
      remainingCreditsSecondary: 0,
    });

    render(<AccountCard account={account} />);

    expect(screen.getByText("Credits:")).toBeInTheDocument();
    expect(screen.getByText("959.00")).toBeInTheDocument();
  });

  it("renders re-auth status and action for re-auth required accounts", () => {
    const account = createAccountSummary({ status: "reauth_required" });

    render(<AccountCard account={account} />);

    expect(screen.getByText("Re-auth required")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Re-auth" })).toBeInTheDocument();
  });

  it("disables the limit warm-up toggle for read-only guests", () => {
    const account = createAccountSummary({
      displayName: "Read Only Account",
      limitWarmupEnabled: false,
    });

    render(<AccountCard account={account} readOnly />);

    expect(screen.getByRole("button", { name: "Enable limit warm-up for Read Only Account" })).toBeDisabled();
  });

  it("shows reset action when reset credits are available", () => {
    const account = createAccountSummary({
      availableResetCredits: 2,
      resetCreditNearestExpiresAt: "2026-01-03T12:00:00.000Z",
    });

    render(<AccountCard account={account} />);

    expect(screen.getByRole("button", { name: "Reset (2)" })).toBeInTheDocument();
  });

  it("hides reset action when no reset credits are available", () => {
    const account = createAccountSummary({ availableResetCredits: 0 });

    render(<AccountCard account={account} />);

    expect(screen.queryByRole("button", { name: /Reset \(/ })).not.toBeInTheDocument();
  });

  it("disables reset action for paused accounts", async () => {
    const user = userEvent.setup();
    const onAction = vi.fn();
    const account = createAccountSummary({
      accountId: "acc-paused",
      displayName: "Paused Account",
      status: "paused",
      availableResetCredits: 1,
      resetCreditNearestExpiresAt: "2026-01-03T12:00:00.000Z",
    });

    render(<AccountCard account={account} onAction={onAction} />);

    const resetButton = screen.getByRole("button", { name: "Reset (1)" });
    expect(resetButton).toBeDisabled();

    await user.click(resetButton);
    expect(onAction).not.toHaveBeenCalledWith(account, "reset-credit");
  });

  it("shows a usage-based seat's live pool instead of window bars", () => {
    // Before this, the card branched on window metadata alone; a seat with no
    // window fell through to the 5h + weekly pair and rendered two empty bars
    // with no dollar figure anywhere.
    render(<AccountCard account={createAccountSummary({
      ...USAGE_BASED_SEAT,
      usageCeilingPrimaryPct: 90,
      usageCeilingSecondaryPct: 90,
    })} />);

    expect(screen.getByText("Extra usage")).toBeInTheDocument();
    expect(screen.getByText("$115.14 of $200.00 left")).toBeInTheDocument();
    expect(screen.queryByTestId("usage-ceiling-marker")).not.toBeInTheDocument();
    expect(screen.queryByText("At ceiling")).not.toBeInTheDocument();
    expect(screen.getByText("58%")).toBeInTheDocument();
    expect(screen.queryByText("5h")).not.toBeInTheDocument();
    expect(screen.queryByText("Weekly")).not.toBeInTheDocument();
  });

  it("keeps a usage-based seat on its plan budget while that has headroom", () => {
    const account = createAccountSummary({
      ...USAGE_BASED_SEAT,
      spendBudget: { ...USAGE_BASED_SEAT.spendBudget, usedPercent: 40, used: 400, remaining: 600 },
    });

    render(<AccountCard account={account} />);

    expect(screen.getByText("Budget")).toBeInTheDocument();
    expect(screen.getByText("$600.00 of $1,000.00 left")).toBeInTheDocument();
    expect(screen.queryByText("Extra usage")).not.toBeInTheDocument();
  });

  it("says so when a usage-based seat has reported no pool yet", () => {
    const account = createAccountSummary({
      ...USAGE_BASED_SEAT,
      spendBudget: null,
      extraCredits: null,
    });

    render(<AccountCard account={account} />);

    expect(screen.getByText("No budget reported yet")).toBeInTheDocument();
    expect(screen.queryByText("5h")).not.toBeInTheDocument();
  });
});

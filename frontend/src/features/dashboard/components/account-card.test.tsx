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
    render(<AccountCard account={createAccountSummary(USAGE_BASED_SEAT)} />);

    expect(screen.getByText("Extra usage")).toBeInTheDocument();
    expect(screen.getByText("$115.14 of $200.00 left")).toBeInTheDocument();
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

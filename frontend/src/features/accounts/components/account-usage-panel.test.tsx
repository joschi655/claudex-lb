import { fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { AccountUsagePanel } from "@/features/accounts/components/account-usage-panel";
import { createAccountSummary, createAccountTrends } from "@/test/mocks/factories";

describe("AccountUsagePanel", () => {
  beforeEach(() => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date("2026-01-01T00:00:00.000Z"));
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it.each([
    { label: "5h", primaryCeiling: 90, secondaryCeiling: null },
    { label: "Weekly", primaryCeiling: null, secondaryCeiling: 90 },
  ])("marks only the configured $label ceiling", ({ label, primaryCeiling, secondaryCeiling }) => {
    const account = createAccountSummary({
      usageCeilingPrimaryPct: primaryCeiling,
      usageCeilingSecondaryPct: secondaryCeiling,
    });

    render(<AccountUsagePanel account={account} trends={null} />);

    expect(screen.getAllByTestId("usage-ceiling-marker")).toHaveLength(1);
    expect(screen.getByTestId("usage-ceiling-marker")).toHaveAttribute("title", `${label} ceiling at 90% used`);
  });

  it("marks both remaining bars at 10% for 90% used ceilings", () => {
    const account = createAccountSummary({
      usageCeilingPrimaryPct: 90,
      usageCeilingSecondaryPct: 90,
    });

    render(<AccountUsagePanel account={account} trends={null} />);

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

    render(<AccountUsagePanel account={account} trends={null} />);

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

    render(<AccountUsagePanel account={account} trends={null} />);

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

    render(<AccountUsagePanel account={account} trends={null} />);

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

    render(<AccountUsagePanel account={account} trends={null} />);

    expect(screen.getAllByTestId("usage-ceiling-marker")).toHaveLength(2);
    expect(screen.queryByText("At ceiling")).not.toBeInTheDocument();
  });

  it("shows '--' for missing quota percent instead of 0%", () => {
    const account = createAccountSummary({
      usage: {
        primaryRemainingPercent: null,
        secondaryRemainingPercent: 67,
      },
      windowMinutesPrimary: 300,
      windowMinutesSecondary: 10_080,
    });

    render(<AccountUsagePanel account={account} trends={null} />);

    expect(screen.getByText("5h remaining")).toBeInTheDocument();
    expect(screen.getByText("--")).toBeInTheDocument();
  });

  it("hides 5h row for weekly-only accounts", () => {
    const account = createAccountSummary({
      planType: "free",
      usage: {
        primaryRemainingPercent: null,
        secondaryRemainingPercent: 76,
      },
      windowMinutesPrimary: null,
      windowMinutesSecondary: 10_080,
    });

    render(<AccountUsagePanel account={account} trends={null} />);

    expect(screen.queryByText("5h remaining")).not.toBeInTheDocument();
    expect(screen.getByText("Weekly remaining")).toBeInTheDocument();
  });

  it("shows only Monthly for monthly-only free accounts", () => {
    const account = createAccountSummary({
      usageCeilingPrimaryPct: 90,
      usageCeilingSecondaryPct: 90,
      planType: "free",
      usage: {
        primaryRemainingPercent: null,
        secondaryRemainingPercent: null,
        monthlyRemainingPercent: 95,
      },
      windowMinutesPrimary: null,
      windowMinutesSecondary: null,
      windowMinutesMonthly: 43_200,
      resetAtPrimary: null,
      resetAtSecondary: null,
      resetAtMonthly: "2026-01-31T00:00:00.000Z",
    });

    render(<AccountUsagePanel account={account} trends={null} />);

    expect(screen.getByText("Monthly remaining")).toBeInTheDocument();
    expect(screen.queryByTestId("usage-ceiling-marker")).not.toBeInTheDocument();
    expect(screen.queryByText("At ceiling")).not.toBeInTheDocument();
    expect(screen.queryByText("5h remaining")).not.toBeInTheDocument();
    expect(screen.queryByText("Weekly remaining")).not.toBeInTheDocument();
  });

  it("renders mapped label for the known gated additional quota limit", () => {
    const account = createAccountSummary({
      usageCeilingPrimaryPct: 90,
      usageCeilingSecondaryPct: 90,
      additionalQuotas: [
        {
          limitName: "codex_spark",
          meteredFeature: "codex_bengalfox",
          routingPolicy: "inherit",
          primaryWindow: {
            usedPercent: 35,
            resetAt: Math.floor(new Date("2026-01-07T13:00:00.000Z").getTime() / 1000),
            windowMinutes: 300,
          },
          secondaryWindow: null,
        },
      ],
    });

    render(<AccountUsagePanel account={account} trends={null} />);

    expect(screen.getByText("Additional Quotas")).toBeInTheDocument();
    expect(screen.getByText("GPT-5.3-Codex-Spark")).toBeInTheDocument();
    expect(screen.getByText(/35% used/)).toBeInTheDocument();
    expect(screen.getByText("Resets in 6d 13h")).toBeInTheDocument();
    expect(screen.getAllByTestId("usage-ceiling-marker")).toHaveLength(2);
  });

  it("renders request log usage summary when available", () => {
    const account = createAccountSummary({
      requestUsage: {
        requestCount: 7,
        totalTokens: 51_480,
        cachedInputTokens: 41_470,
        totalCostUsd: 0.13,
      },
    });

    render(<AccountUsagePanel account={account} trends={null} />);

    expect(screen.getByText("Request logs total")).toBeInTheDocument();
    expect(screen.getByText(/\$0\.13/)).toBeInTheDocument();
    expect(screen.getByText(/51\.48K tok/)).toBeInTheDocument();
  });

  it("renders usage reset credit availability when provided", () => {
    const account = createAccountSummary();

    render(
      <AccountUsagePanel
        account={account}
        trends={null}
        resetCredits={{ availableCount: 3 }}
      />,
    );

    expect(screen.getByText("Usage resets")).toBeInTheDocument();
    expect(screen.getByText("3 available")).toBeInTheDocument();
  });

  it("renders a usage reset action when provided", () => {
    const account = createAccountSummary({ accountId: "acc_reset" });
    const onReset = vi.fn();

    render(
      <AccountUsagePanel
        account={account}
        trends={null}
        resetCredits={{ availableCount: 1 }}
        onReset={onReset}
      />,
    );

    fireEvent.click(screen.getByRole("button", { name: "Reset usage" }));

    expect(onReset).toHaveBeenCalledWith("acc_reset");
    expect(onReset).toHaveBeenCalledTimes(1);
  });

  it("shows the weekly plan legend when scheduled trend data exists", () => {
    const account = createAccountSummary();
    const trends = createAccountTrends(account.accountId, {
      secondaryScheduled: [
        { t: "2026-01-01T00:00:00.000Z", v: 100 },
        { t: "2026-01-01T01:00:00.000Z", v: 99.4 },
      ],
    });

    render(<AccountUsagePanel account={account} trends={trends} />);

    expect(screen.getByText("Weekly plan")).toBeInTheDocument();
  });

  it("shows trends when only secondary scheduled trend points are present", () => {
    const account = createAccountSummary();
    const trends = createAccountTrends(account.accountId, {
      primary: [],
      secondary: [],
      secondaryScheduled: [
        { t: "2026-01-01T00:00:00.000Z", v: 100 },
        { t: "2026-01-01T06:00:00.000Z", v: 92 },
      ],
    });

    render(<AccountUsagePanel account={account} trends={trends} />);

    expect(screen.getByText("7-day trend")).toBeInTheDocument();
    expect(screen.getByText("Weekly plan")).toBeInTheDocument();
  });

  it("shows the spend budget for a seat that reports no window", () => {
    const account = createAccountSummary({
      usageCeilingPrimaryPct: 90,
      usageCeilingSecondaryPct: 90,
      planType: "claude_enterprise",
      usage: {
        primaryRemainingPercent: null,
        secondaryRemainingPercent: null,
      },
      windowMinutesPrimary: null,
      windowMinutesSecondary: null,
      spendBudget: {
        usedPercent: 77.72440259999999,
        used: 777.244026,
        limit: 1000,
        remaining: 222.755974,
        currency: "USD",
        resetAt: "2026-09-30T20:47:10.939005Z",
      },
    });

    render(<AccountUsagePanel account={account} trends={null} />);

    expect(screen.getByText("Budget used")).toBeInTheDocument();
    expect(screen.queryByTestId("usage-ceiling-marker")).not.toBeInTheDocument();
    expect(screen.queryByText("At ceiling")).not.toBeInTheDocument();
    expect(screen.getByText("77.7%")).toBeInTheDocument();
    expect(screen.getByText(/\$777\.24 of \$1,000\.00/)).toBeInTheDocument();
    expect(screen.getByText(/\$222\.76 left/)).toBeInTheDocument();
    // The budget replaces the window bars rather than sitting beside empty ones.
    expect(screen.queryByText("5h remaining")).not.toBeInTheDocument();
    expect(screen.queryByText("Weekly remaining")).not.toBeInTheDocument();
  });

  it("shows the extra-usage pool alongside the windows for a Pro seat", () => {
    const account = createAccountSummary({
      planType: "claude_pro",
      usage: { primaryRemainingPercent: 80, secondaryRemainingPercent: 60 },
      windowMinutesPrimary: 300,
      windowMinutesSecondary: 10_080,
      extraCredits: {
        enabled: true,
        usedPercent: 8.015,
        used: 16.03,
        limit: 200,
        remaining: 183.97,
        currency: "USD",
      },
    });

    render(<AccountUsagePanel account={account} trends={null} />);

    expect(screen.getByText("Extra usage")).toBeInTheDocument();
    expect(screen.getByText("8.0%")).toBeInTheDocument();
    expect(screen.getByText(/\$16\.03 of \$200\.00/)).toBeInTheDocument();
    expect(screen.getByText(/\$183\.97 left/)).toBeInTheDocument();
  });

  it("reports a switched-off extra-usage pool rather than hiding it", () => {
    const account = createAccountSummary({
      planType: "claude_pro",
      usage: { primaryRemainingPercent: 80, secondaryRemainingPercent: 60 },
      windowMinutesPrimary: 300,
      windowMinutesSecondary: 10_080,
      extraCredits: {
        enabled: false,
        usedPercent: 0,
        used: null,
        limit: null,
        remaining: null,
        currency: "USD",
      },
    });

    render(<AccountUsagePanel account={account} trends={null} />);

    expect(screen.getByText("Extra usage")).toBeInTheDocument();
    expect(screen.getByText("Off")).toBeInTheDocument();
  });

  it("shows no extra-usage row for an account that reports no pool", () => {
    const account = createAccountSummary({
      usage: { primaryRemainingPercent: 80, secondaryRemainingPercent: 60 },
      windowMinutesPrimary: 300,
      windowMinutesSecondary: 10_080,
    });

    render(<AccountUsagePanel account={account} trends={null} />);

    expect(screen.queryByText("Extra usage")).not.toBeInTheDocument();
  });

  it("shows no budget row for a window-based account", () => {
    const account = createAccountSummary({
      usage: { primaryRemainingPercent: 80, secondaryRemainingPercent: 60 },
      windowMinutesPrimary: 300,
      windowMinutesSecondary: 10_080,
    });

    render(<AccountUsagePanel account={account} trends={null} />);

    expect(screen.getByText("5h remaining")).toBeInTheDocument();
    expect(screen.queryByText("Budget used")).not.toBeInTheDocument();
  });
});

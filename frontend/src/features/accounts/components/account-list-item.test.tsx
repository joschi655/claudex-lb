import { render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { AccountListItem } from "@/features/accounts/components/account-list-item";
import { useAccountQuotaDisplayStore } from "@/hooks/use-account-quota-display";
import { createAccountSummary } from "@/test/mocks/factories";

describe("AccountListItem", () => {
  beforeEach(() => {
    useAccountQuotaDisplayStore.setState({ quotaDisplay: "both" });
    vi.useFakeTimers();
    vi.setSystemTime(new Date("2026-01-01T12:00:00.000Z"));
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it("renders neutral quota track when secondary remaining percent is unknown", () => {
    const account = createAccountSummary({
      usage: {
        primaryRemainingPercent: 82,
        secondaryRemainingPercent: null,
      },
    });

    render(<AccountListItem account={account} selected={false} onSelect={vi.fn()} />);

    expect(screen.getByTestId("mini-quota-track-weekly")).toHaveClass("bg-muted");
    expect(screen.queryByTestId("mini-quota-track-weekly-fill")).not.toBeInTheDocument();
    expect(screen.getByText("5h")).toBeInTheDocument();
    expect(screen.getByText("Weekly")).toBeInTheDocument();
    expect(screen.getByText("Reset in 1h")).toBeInTheDocument();
    expect(screen.getByText("Reset in 1d")).toBeInTheDocument();
  });

  it("omits the 5h row for weekly-only accounts", () => {
    const account = createAccountSummary({
      usage: {
        primaryRemainingPercent: null,
        secondaryRemainingPercent: 73,
      },
      resetAtPrimary: null,
      resetAtSecondary: "2026-01-02T12:00:00.000Z",
      windowMinutesPrimary: null,
      windowMinutesSecondary: 10_080,
    });

    render(<AccountListItem account={account} selected={false} onSelect={vi.fn()} />);

    expect(screen.queryByText("5h")).not.toBeInTheDocument();
    expect(screen.getByText("Weekly")).toBeInTheDocument();
    expect(screen.getByText("Reset in 1d")).toBeInTheDocument();
  });

  it("shows only the monthly row for monthly-only accounts", () => {
    const account = createAccountSummary({
      planType: "free",
      usage: {
        primaryRemainingPercent: null,
        secondaryRemainingPercent: null,
        monthlyRemainingPercent: 73,
      },
      resetAtPrimary: null,
      resetAtSecondary: null,
      resetAtMonthly: "2026-01-31T12:00:00.000Z",
      windowMinutesPrimary: null,
      windowMinutesSecondary: null,
      windowMinutesMonthly: 43_200,
    });

    render(<AccountListItem account={account} selected={false} onSelect={vi.fn()} />);

    expect(screen.queryByText("5h")).not.toBeInTheDocument();
    expect(screen.queryByText("Weekly")).not.toBeInTheDocument();
    expect(screen.getByText("Monthly")).toBeInTheDocument();
  });

  it("renders legacy primary quota data without window metadata", () => {
    const account = createAccountSummary({
      usage: {
        primaryRemainingPercent: 64,
        secondaryRemainingPercent: null,
      },
      resetAtPrimary: "2026-01-01T13:00:00.000Z",
      resetAtSecondary: null,
      windowMinutesPrimary: null,
      windowMinutesSecondary: null,
    });

    render(<AccountListItem account={account} selected={false} onSelect={vi.fn()} />);

    expect(screen.getByText("5h")).toBeInTheDocument();
    expect(screen.getByTestId("mini-quota-track-5h-fill")).toHaveStyle({ width: "64%" });
    expect(screen.getByText("Reset in 1h")).toBeInTheDocument();
    expect(screen.queryByText("Weekly")).not.toBeInTheDocument();
  });

  it("does not duplicate unavailable reset labels", () => {
    const account = createAccountSummary({
      usage: {
        primaryRemainingPercent: 64,
        secondaryRemainingPercent: null,
      },
      resetAtPrimary: null,
      resetAtSecondary: null,
      windowMinutesPrimary: 300,
      windowMinutesSecondary: null,
    });

    render(<AccountListItem account={account} selected={false} onSelect={vi.fn()} />);

    expect(screen.getByText("Reset --")).toBeInTheDocument();
    expect(screen.queryByText("Reset Reset unavailable")).not.toBeInTheDocument();
  });

  it("shows only the 5h row when the account quota preference is 5h", () => {
    useAccountQuotaDisplayStore.setState({ quotaDisplay: "5h" });

    const account = createAccountSummary({
      usage: {
        primaryRemainingPercent: 82,
        secondaryRemainingPercent: 73,
      },
    });

    render(<AccountListItem account={account} selected={false} onSelect={vi.fn()} />);

    expect(screen.getByText("5h")).toBeInTheDocument();
    expect(screen.queryByText("Weekly")).not.toBeInTheDocument();
  });

  it("renders quota fill when secondary remaining percent is available", () => {
    const account = createAccountSummary({
      usage: {
        primaryRemainingPercent: 82,
        secondaryRemainingPercent: 73,
      },
    });

    render(<AccountListItem account={account} selected={false} onSelect={vi.fn()} />);

    expect(screen.getByTestId("mini-quota-track-weekly-fill")).toHaveStyle({ width: "73%" });
  });

  it("marks burn-first accounts in the list", () => {
    const account = createAccountSummary({ routingPolicy: "burn_first" });

    render(<AccountListItem account={account} selected={false} onSelect={vi.fn()} />);

    expect(screen.getByText("Burn first")).toBeInTheDocument();
  });

  it("marks preserved accounts in the list", () => {
    const account = createAccountSummary({ routingPolicy: "preserve" });

    render(<AccountListItem account={account} selected={false} onSelect={vi.fn()} />);

    expect(screen.getByText("Preserve")).toBeInTheDocument();
  });

  it("marks normal accounts in the list", () => {
    const account = createAccountSummary({ routingPolicy: "normal" });

    render(<AccountListItem account={account} selected={false} onSelect={vi.fn()} />);

    expect(screen.getByText("Normal")).toBeInTheDocument();
  });

  it("hides routing policy badges for accounts that require operator recovery", () => {
    const { rerender } = render(
      <AccountListItem
        account={createAccountSummary({ routingPolicy: "normal", status: "reauth_required" })}
        selected={false}
        onSelect={vi.fn()}
      />,
    );

    expect(screen.getByText("Re-auth required")).toBeInTheDocument();
    expect(screen.queryByText("Normal")).not.toBeInTheDocument();

    rerender(
      <AccountListItem
        account={createAccountSummary({ routingPolicy: "preserve", status: "deactivated" })}
        selected={false}
        onSelect={vi.fn()}
      />,
    );

    expect(screen.getByText("Deactivated")).toBeInTheDocument();
    expect(screen.queryByText("Preserve")).not.toBeInTheDocument();
  });

  it("keeps workspace context visible when a display alias uses the email subtitle", () => {
    const account = createAccountSummary({
      displayName: "Work seat",
      email: "work@example.com",
      planType: "team",
      chatgptAccountId: null,
      workspaceLabel: "Design Workspace",
      seatType: "member",
    });

    render(<AccountListItem account={account} selected={false} onSelect={vi.fn()} />);

    expect(screen.getByText("Work seat")).toBeInTheDocument();
    expect(
      screen.getByText((_, element) => element?.textContent === "work@example.com | Team | Design Workspace | Member"),
    ).toBeInTheDocument();
  });

  it("uses ChatGPT account id before workspace metadata or unknown fallback", () => {
    const account = createAccountSummary({
      planType: "team",
      workspaceId: "legacy-workspace-id",
      workspaceLabel: "Legacy Workspace",
      chatgptAccountId: "chatgpt-workspace-123",
    });

    render(<AccountListItem account={account} selected={false} onSelect={vi.fn()} />);

    expect(screen.getByText("Team | chatgpt-workspace-123")).toBeInTheDocument();
    expect(screen.queryByText(/Legacy Workspace/)).not.toBeInTheDocument();
    expect(screen.queryByText(/Personal \/ unknown workspace/)).not.toBeInTheDocument();
  });

  it("shows a reset-credit badge capped at 99+", () => {
    const account = createAccountSummary({ availableResetCredits: 120 });

    render(<AccountListItem account={account} selected={false} onSelect={vi.fn()} />);

    expect(screen.getByText("99+")).toBeInTheDocument();
  });

  it("shows the reset-credit badge count when below the cap", () => {
    const account = createAccountSummary({ availableResetCredits: 3 });

    render(<AccountListItem account={account} selected={false} onSelect={vi.fn()} />);

    expect(screen.getByText("3")).toBeInTheDocument();
  });

  it("marks the account the pool named as next", () => {
    const account = createAccountSummary({ status: "active" });

    render(
      <AccountListItem
        account={account}
        selected={false}
        nextUp={{ certain: true }}
        onSelect={vi.fn()}
      />,
    );

    expect(screen.getByText("Next")).toBeInTheDocument();
    // The badge replaces the status: being next already says the account can serve.
    expect(screen.queryByText("Active")).not.toBeInTheDocument();
  });

  it("hedges when the pool reported the answer as uncertain", () => {
    const account = createAccountSummary({ status: "active" });

    render(
      <AccountListItem
        account={account}
        selected={false}
        nextUp={{ certain: false }}
        onSelect={vi.fn()}
      />,
    );

    expect(screen.getByText("Likely next")).toBeInTheDocument();
  });

  it("shows the status when this account is not next", () => {
    const account = createAccountSummary({ status: "active" });

    render(<AccountListItem account={account} selected={false} onSelect={vi.fn()} />);

    expect(screen.queryByText("Next")).not.toBeInTheDocument();
    expect(screen.queryByText("Likely next")).not.toBeInTheDocument();
  });

  it("shows the pin beside the routing policy, not instead of it", () => {
    // The two are orthogonal now: a preserved seat that is pinned is still
    // preserved, and the list has to say so or the pin looks destructive.
    const account = createAccountSummary({ pinned: true, routingPolicy: "preserve" });

    render(<AccountListItem account={account} selected={false} onSelect={vi.fn()} />);

    expect(screen.getByText("Pinned")).toBeInTheDocument();
    expect(screen.getByText("Preserve")).toBeInTheDocument();
  });

  it("shows no pin for an unpinned account", () => {
    const account = createAccountSummary({ pinned: false, routingPolicy: "normal" });

    render(<AccountListItem account={account} selected={false} onSelect={vi.fn()} />);

    expect(screen.queryByText("Pinned")).not.toBeInTheDocument();
    expect(screen.getByText("Normal")).toBeInTheDocument();
  });

  it("hides the reset-credit badge when no credits are available", () => {
    const account = createAccountSummary({ availableResetCredits: 0 });

    render(<AccountListItem account={account} selected={false} onSelect={vi.fn()} />);

    expect(screen.queryByText("99+")).not.toBeInTheDocument();
  });
});

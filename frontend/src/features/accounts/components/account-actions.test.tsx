import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { AccountActions } from "@/features/accounts/components/account-actions";
import { createAccountSummary } from "@/test/mocks/factories";

describe("AccountActions", () => {
  it("renders an explicit routing policy selector", async () => {
    const onRoutingPolicyChange = vi.fn();
    const account = createAccountSummary({ routingPolicy: "normal" });

    render(
      <AccountActions
        account={account}
        busy={false}
        onPause={vi.fn()}
        onResume={vi.fn()}
        onProbe={vi.fn()}
        onDelete={vi.fn()}
        onReauth={vi.fn()}
        onExportAuth={vi.fn()}
        onResetCredit={vi.fn()}
        onSecurityWorkAuthorizedChange={vi.fn()}
        onLimitWarmupChange={vi.fn()}
        onRoutingPolicyChange={onRoutingPolicyChange}
        onPinChange={vi.fn()}
        onQuotaKindChange={vi.fn()}
        onPaceGatesChange={() => {}}
      />,
    );

    expect(screen.getByText("Routing policy")).toBeInTheDocument();
    expect(
      screen.getByRole("combobox", { name: "Routing policy" }),
    ).toHaveTextContent("Normal");
  });

  it("keeps the pin out of the routing policy selector", async () => {
    // The pin used to be a fourth policy value, which made pinning a preserved
    // seat destroy the fact that it was preserved.
    const user = userEvent.setup();
    const account = createAccountSummary({ routingPolicy: "preserve" });

    render(
      <AccountActions
        account={account}
        busy={false}
        onPause={vi.fn()}
        onResume={vi.fn()}
        onProbe={vi.fn()}
        onDelete={vi.fn()}
        onReauth={vi.fn()}
        onExportAuth={vi.fn()}
        onResetCredit={vi.fn()}
        onSecurityWorkAuthorizedChange={vi.fn()}
        onLimitWarmupChange={vi.fn()}
        onRoutingPolicyChange={vi.fn()}
        onPinChange={vi.fn()}
        onQuotaKindChange={vi.fn()}
        onPaceGatesChange={() => {}}
      />,
    );

    await user.click(screen.getByRole("combobox", { name: "Routing policy" }));

    expect(screen.getByRole("option", { name: "Normal" })).toBeInTheDocument();
    expect(screen.getByRole("option", { name: "Preserve" })).toBeInTheDocument();
    expect(screen.getByRole("option", { name: "Burn first" })).toBeInTheDocument();
    expect(screen.queryByRole("option", { name: "Pinned" })).not.toBeInTheDocument();
  });

  it("pins through its own control, leaving the policy where it was", async () => {
    const user = userEvent.setup();
    const onPinChange = vi.fn();
    const onRoutingPolicyChange = vi.fn();
    const account = createAccountSummary({ routingPolicy: "preserve", pinned: false });

    render(
      <AccountActions
        account={account}
        busy={false}
        onPause={vi.fn()}
        onResume={vi.fn()}
        onProbe={vi.fn()}
        onDelete={vi.fn()}
        onReauth={vi.fn()}
        onExportAuth={vi.fn()}
        onResetCredit={vi.fn()}
        onSecurityWorkAuthorizedChange={vi.fn()}
        onLimitWarmupChange={vi.fn()}
        onRoutingPolicyChange={onRoutingPolicyChange}
        onPinChange={onPinChange}
        onQuotaKindChange={vi.fn()}
        onPaceGatesChange={() => {}}
      />,
    );

    await user.click(screen.getByRole("switch", { name: /Pin to this account/i }));

    expect(onPinChange).toHaveBeenCalledWith(account.accountId, true);
    expect(onRoutingPolicyChange).not.toHaveBeenCalled();
    expect(
      screen.getByRole("combobox", { name: "Routing policy" }),
    ).toHaveTextContent("Preserve");
  });

  it("unpins a pinned account", async () => {
    const user = userEvent.setup();
    const onPinChange = vi.fn();
    const account = createAccountSummary({ pinned: true });

    render(
      <AccountActions
        account={account}
        busy={false}
        onPause={vi.fn()}
        onResume={vi.fn()}
        onProbe={vi.fn()}
        onDelete={vi.fn()}
        onReauth={vi.fn()}
        onExportAuth={vi.fn()}
        onResetCredit={vi.fn()}
        onSecurityWorkAuthorizedChange={vi.fn()}
        onLimitWarmupChange={vi.fn()}
        onRoutingPolicyChange={vi.fn()}
        onPinChange={onPinChange}
        onQuotaKindChange={vi.fn()}
        onPaceGatesChange={() => {}}
      />,
    );

    await user.click(screen.getByRole("switch", { name: /Pin to this account/i }));

    expect(onPinChange).toHaveBeenCalledWith(account.accountId, false);
  });

  it("renders re-authenticate action for re-auth required accounts", () => {
    const onReauth = vi.fn();
    const account = createAccountSummary({ status: "reauth_required" });

    render(
      <AccountActions
        account={account}
        busy={false}
        onPause={vi.fn()}
        onResume={vi.fn()}
        onProbe={vi.fn()}
        onDelete={vi.fn()}
        onReauth={onReauth}
        onExportAuth={vi.fn()}
        onResetCredit={vi.fn()}
        onSecurityWorkAuthorizedChange={vi.fn()}
        onLimitWarmupChange={vi.fn()}
        onRoutingPolicyChange={vi.fn()}
        onPinChange={vi.fn()}
        onQuotaKindChange={vi.fn()}
        onPaceGatesChange={() => {}}
      />,
    );

    expect(
      screen.getByRole("button", { name: "Re-authenticate" }),
    ).toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: "Pause" }),
    ).not.toBeInTheDocument();
    expect(
      screen.queryByRole("combobox", { name: "Routing policy" }),
    ).not.toBeInTheDocument();
  });

  it("fires the per-account probe callback for active accounts", async () => {
    const user = userEvent.setup();
    const account = createAccountSummary();
    const onProbe = vi.fn();

    render(
      <AccountActions
        account={account}
        busy={false}
        onPause={vi.fn()}
        onResume={vi.fn()}
        onProbe={onProbe}
        onDelete={vi.fn()}
        onReauth={vi.fn()}
        onExportAuth={vi.fn()}
        onResetCredit={vi.fn()}
        onSecurityWorkAuthorizedChange={vi.fn()}
        onLimitWarmupChange={vi.fn()}
        onRoutingPolicyChange={vi.fn()}
        onPinChange={vi.fn()}
        onQuotaKindChange={vi.fn()}
        onPaceGatesChange={() => {}}
      />,
    );

    await user.click(screen.getByRole("button", { name: "Force probe" }));

    expect(onProbe).toHaveBeenCalledWith(account.accountId);
    expect(onProbe).toHaveBeenCalledTimes(1);
  });

  it.each(["paused", "deactivated"] as const)(
    "disables force probe for %s accounts",
    async (status) => {
      const user = userEvent.setup();
      const account = createAccountSummary({ status });
      const onProbe = vi.fn();

      render(
        <AccountActions
          account={account}
          busy={false}
          onPause={vi.fn()}
          onResume={vi.fn()}
          onProbe={onProbe}
          onDelete={vi.fn()}
          onReauth={vi.fn()}
          onExportAuth={vi.fn()}
          onResetCredit={vi.fn()}
          onSecurityWorkAuthorizedChange={vi.fn()}
          onLimitWarmupChange={vi.fn()}
          onRoutingPolicyChange={vi.fn()}
          onPinChange={vi.fn()}
          onQuotaKindChange={vi.fn()}
          onPaceGatesChange={() => {}}
        />,
      );

      const button = screen.getByRole("button", { name: "Force probe" });
      expect(button).toBeDisabled();

      await user.click(button);

      expect(onProbe).not.toHaveBeenCalled();
    },
  );

  it("disables force probe in read-only mode", async () => {
    const user = userEvent.setup();
    const account = createAccountSummary();
    const onProbe = vi.fn();

    render(
      <AccountActions
        account={account}
        busy={false}
        readOnly
        onPause={vi.fn()}
        onResume={vi.fn()}
        onProbe={onProbe}
        onDelete={vi.fn()}
        onReauth={vi.fn()}
        onExportAuth={vi.fn()}
        onResetCredit={vi.fn()}
        onSecurityWorkAuthorizedChange={vi.fn()}
        onLimitWarmupChange={vi.fn()}
        onRoutingPolicyChange={vi.fn()}
        onPinChange={vi.fn()}
        onQuotaKindChange={vi.fn()}
        onPaceGatesChange={() => {}}
      />,
    );

    const button = screen.getByRole("button", { name: "Force probe" });
    expect(button).toBeDisabled();

    await user.click(button);

    expect(onProbe).not.toHaveBeenCalled();
  });

  it("shows reset action when reset credits are available", async () => {
    const user = userEvent.setup();
    const onResetCredit = vi.fn();
    const account = createAccountSummary({
      availableResetCredits: 3,
      resetCreditNearestExpiresAt: "2026-01-03T12:00:00.000Z",
    });

    render(
      <AccountActions
        account={account}
        busy={false}
        onPause={vi.fn()}
        onResume={vi.fn()}
        onProbe={vi.fn()}
        onDelete={vi.fn()}
        onReauth={vi.fn()}
        onExportAuth={vi.fn()}
        onResetCredit={onResetCredit}
        onSecurityWorkAuthorizedChange={vi.fn()}
        onLimitWarmupChange={vi.fn()}
        onRoutingPolicyChange={vi.fn()}
        onPinChange={vi.fn()}
        onQuotaKindChange={vi.fn()}
        onPaceGatesChange={() => {}}
      />,
    );

    await user.click(screen.getByRole("button", { name: "Reset (3)" }));

    expect(onResetCredit).toHaveBeenCalledWith(account.accountId);
  });

  it.each(["paused", "deactivated", "reauth_required"] as const)(
    "disables reset action for %s accounts",
    async (status) => {
      const user = userEvent.setup();
      const onResetCredit = vi.fn();
      const account = createAccountSummary({
        status,
        availableResetCredits: 2,
        resetCreditNearestExpiresAt: "2026-01-03T12:00:00.000Z",
      });

      render(
        <AccountActions
          account={account}
          busy={false}
          onPause={vi.fn()}
          onResume={vi.fn()}
          onProbe={vi.fn()}
          onDelete={vi.fn()}
          onReauth={vi.fn()}
          onExportAuth={vi.fn()}
          onResetCredit={onResetCredit}
          onSecurityWorkAuthorizedChange={vi.fn()}
          onLimitWarmupChange={vi.fn()}
          onRoutingPolicyChange={vi.fn()}
          onPinChange={vi.fn()}
          onQuotaKindChange={vi.fn()}
          onPaceGatesChange={() => {}}
        />,
      );

      const button = screen.getByRole("button", { name: "Reset (2)" });
      expect(button).toBeDisabled();
      await user.click(button);
      expect(onResetCredit).not.toHaveBeenCalled();
    },
  );

  it("hides reset action when no reset credits are available", () => {
    const account = createAccountSummary({
      availableResetCredits: 0,
      resetCreditNearestExpiresAt: null,
    });

    render(
      <AccountActions
        account={account}
        busy={false}
        onPause={vi.fn()}
        onResume={vi.fn()}
        onProbe={vi.fn()}
        onDelete={vi.fn()}
        onReauth={vi.fn()}
        onExportAuth={vi.fn()}
        onResetCredit={vi.fn()}
        onSecurityWorkAuthorizedChange={vi.fn()}
        onLimitWarmupChange={vi.fn()}
        onRoutingPolicyChange={vi.fn()}
        onPinChange={vi.fn()}
        onQuotaKindChange={vi.fn()}
        onPaceGatesChange={() => {}}
      />,
    );

    expect(screen.queryByRole("button", { name: /Reset \(/ })).not.toBeInTheDocument();
  });
});

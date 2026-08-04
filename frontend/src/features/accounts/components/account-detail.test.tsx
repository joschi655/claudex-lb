import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { ReactElement } from "react";
import { describe, expect, it, vi } from "vitest";

import { AccountDetail } from "@/features/accounts/components/account-detail";
import { createAccountSummary, createUpstreamProxyAdmin } from "@/test/mocks/factories";

function renderWithClient(ui: ReactElement) {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(<QueryClientProvider client={queryClient}>{ui}</QueryClientProvider>);
}

describe("AccountDetail", () => {
  it("lets operators change account routing policy", async () => {
    const user = userEvent.setup();
    const onRoutingPolicyChange = vi.fn();
    const account = createAccountSummary({ routingPolicy: "normal" });

    renderWithClient(
      <AccountDetail
        account={account}
        busy={false}
        onPause={vi.fn()}
        onResume={vi.fn()}
        onProbe={vi.fn()}
        onResetUsage={vi.fn()}
        onSetAlias={vi.fn().mockResolvedValue(undefined)}
        onDelete={vi.fn()}
        onReauth={vi.fn()}
        onReplaceAnthropicApiKey={vi.fn()}
        onExportAuth={vi.fn()}
        onResetCredit={vi.fn()}
        onLimitWarmupChange={vi.fn()}
        onRoutingPolicyChange={onRoutingPolicyChange}
        onSecurityWorkAuthorizedChange={vi.fn()}
      />,
    );

    await user.click(screen.getByRole("combobox", { name: "Routing policy" }));
    await user.click(await screen.findByRole("option", { name: "Preserve" }));

    expect(onRoutingPolicyChange).toHaveBeenCalledWith(account.accountId, "preserve");
  });

  it("disables alias and proxy binding controls for read-only guests", () => {
    const onSetAlias = vi.fn().mockResolvedValue(undefined);
    const onProxyBindingSave = vi.fn().mockResolvedValue(undefined);
    const account = createAccountSummary({ accountId: "acc_primary", alias: "Personal" });

    renderWithClient(
      <AccountDetail
        account={account}
        busy={false}
        readOnly
        onPause={vi.fn()}
        onResume={vi.fn()}
        onProbe={vi.fn()}
        onResetUsage={vi.fn()}
        onSetAlias={onSetAlias}
        onDelete={vi.fn()}
        onReauth={vi.fn()}
        onReplaceAnthropicApiKey={vi.fn()}
        onExportAuth={vi.fn()}
        onResetCredit={vi.fn()}
        onLimitWarmupChange={vi.fn()}
        onRoutingPolicyChange={vi.fn()}
        onSecurityWorkAuthorizedChange={vi.fn()}
        onProxyBindingSave={onProxyBindingSave}
        upstreamProxyAdmin={createUpstreamProxyAdmin({
          bindings: [{ accountId: "acc_primary", poolId: "pool_primary", isActive: true }],
        })}
        resetCredits={{ availableCount: 1 }}
      />,
    );

    expect(screen.getByRole("button", { name: "Edit alias" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Reset usage" })).toBeDisabled();
    expect(screen.getByRole("switch", { name: "Enable account proxy binding" })).toBeDisabled();
    expect(screen.getByRole("combobox", { name: "Account proxy pool" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Save binding" })).toBeDisabled();
  });

  it("disables usage reset for paused accounts", () => {
    const account = createAccountSummary({ status: "paused" });

    renderWithClient(
      <AccountDetail
        account={account}
        busy={false}
        onPause={vi.fn()}
        onResume={vi.fn()}
        onProbe={vi.fn()}
        onResetUsage={vi.fn()}
        onSetAlias={vi.fn().mockResolvedValue(undefined)}
        onDelete={vi.fn()}
        onReauth={vi.fn()}
        onReplaceAnthropicApiKey={vi.fn()}
        onExportAuth={vi.fn()}
        onResetCredit={vi.fn()}
        onLimitWarmupChange={vi.fn()}
        onRoutingPolicyChange={vi.fn()}
        onSecurityWorkAuthorizedChange={vi.fn()}
        resetCredits={{ availableCount: 2 }}
      />,
    );

    expect(screen.getByRole("button", { name: "Reset usage" })).toBeDisabled();
  });

  it("renders Claude throughput limits without OpenAI token or proxy panels", () => {
    const account = createAccountSummary({
      provider: "anthropic",
      credentialKind: "anthropic_api_key",
      planType: "claude_api",
      auth: null,
      additionalQuotas: [
        {
          quotaKey: "anthropic_input_tokens",
          limitName: "input_tokens",
          meteredFeature: "input_tokens",
          displayLabel: "Input tokens",
          primaryWindow: { usedPercent: 25, resetAt: 2_000_000_000, windowMinutes: 1 },
        },
      ],
    });

    renderWithClient(
      <AccountDetail
        account={account}
        busy={false}
        onPause={vi.fn()}
        onResume={vi.fn()}
        onProbe={vi.fn()}
        onResetUsage={vi.fn()}
        onSetAlias={vi.fn().mockResolvedValue(undefined)}
        onDelete={vi.fn()}
        onReauth={vi.fn()}
        onReplaceAnthropicApiKey={vi.fn()}
        onExportAuth={vi.fn()}
        onResetCredit={vi.fn()}
        onLimitWarmupChange={vi.fn()}
        onRoutingPolicyChange={vi.fn()}
        onSecurityWorkAuthorizedChange={vi.fn()}
        onProxyBindingSave={vi.fn().mockResolvedValue(undefined)}
        upstreamProxyAdmin={createUpstreamProxyAdmin()}
      />,
    );

    expect(screen.getByText("Claude API rate limits")).toBeInTheDocument();
    expect(screen.getByText("Input tokens")).toBeInTheDocument();
    expect(screen.queryByText("Access token")).not.toBeInTheDocument();
    expect(screen.queryByText("Upstream proxy")).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Reset usage" })).not.toBeInTheDocument();
  });
});

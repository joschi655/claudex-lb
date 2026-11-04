import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { HttpResponse, http } from "msw";
import { toast } from "sonner";
import { describe, expect, it, vi } from "vitest";

import type { AccountSummary } from "@/features/accounts/schemas";
import type { ApiKey, ApiKeyAccountRoutingRule } from "@/features/api-keys/schemas";
import { createAccountSummary, createApiKey } from "@/test/mocks/factories";
import { server } from "@/test/mocks/server";
import { renderWithProviders } from "@/test/utils";

import { AccountRoutingDialog } from "./account-routing-dialog";
import { ApiKeysSection } from "./api-keys-section";

const first = createAccountSummary({
  accountId: "first", alias: "Shared seat", provider: "openai", routingPolicy: "burn_first",
  usageCeilingPrimaryPct: 90,
});
const second = createAccountSummary({
  accountId: "second", displayName: "Second seat", provider: "anthropic", status: "paused",
  usageCeilingPrimaryPct: 95, usageCeilingSecondaryPct: 80,
  paceMarginPrimaryPct: 0, paceMarginSecondaryPct: 10, preResetWindowMinutes: 15,
});
const existingRule: ApiKeyAccountRoutingRule = {
  accountId: "first", routingPolicy: "normal", overrideGates: true,
  usageCeilingPrimaryPct: 75, usageCeilingSecondaryPct: null,
  paceMarginPrimaryPct: 0, paceMarginSecondaryPct: null, preResetWindowMinutes: 0,
};

function mockAccounts(accounts: AccountSummary[] = [first, second]) {
  server.use(http.get("/api/accounts", () => HttpResponse.json({ accounts })));
}

function renderDialog(apiKey = createApiKey(), onSubmit = vi.fn().mockResolvedValue(undefined)) {
  const onOpenChange = vi.fn();
  const props = { open: true, busy: false, apiKey, onSubmit, onOpenChange };
  return { ...renderWithProviders(<AccountRoutingDialog {...props} />), props, onSubmit, onOpenChange };
}

function renderSection(apiKey: ApiKey) {
  server.use(http.get("/api/api-keys/", () => HttpResponse.json([apiKey])));
  return renderWithProviders(
    <ApiKeysSection apiKeyAuthEnabled hideUpstreamQuotaFromApiKeys={false}
      onApiKeyAuthEnabledChange={vi.fn()} onHideUpstreamQuotaFromApiKeysChange={vi.fn()} />,
  );
}

async function openRouting(user: ReturnType<typeof userEvent.setup>) {
  await user.click(await screen.findByRole("button", { name: "Actions" }));
  await user.click(screen.getByRole("menuitem", { name: "Account routing" }));
  return screen.findByRole("dialog", { name: "Account routing" });
}

async function selectOption(user: ReturnType<typeof userEvent.setup>, row: HTMLElement, label: string, option: string) {
  await user.click(within(row).getByRole("combobox", { name: new RegExp(`^${label} for `) }));
  await user.click(await screen.findByRole("option", { name: option }));
}

describe("AccountRoutingDialog", () => {
  it("opens from the table, edits priority and custom gates, and PUTs the full replacement", async () => {
    const user = userEvent.setup();
    const apiKey = createApiKey({ accountRoutingRules: [existingRule] });
    mockAccounts();
    const received: unknown[] = [];
    const expectedRules = [existingRule, {
      accountId: "second", routingPolicy: "preserve", overrideGates: true,
      usageCeilingPrimaryPct: 85.5, usageCeilingSecondaryPct: null,
      paceMarginPrimaryPct: 0, paceMarginSecondaryPct: 10, preResetWindowMinutes: 15,
    }];
    server.use(http.put(`/api/api-keys/${apiKey.id}/account-routing-rules`, async ({ request }) => {
      received.push(await request.json());
      return HttpResponse.json({ ...apiKey, accountRoutingRules: expectedRules });
    }));
    renderSection(apiKey);
    await openRouting(user);

    const firstRow = await screen.findByRole("group", { name: "Shared seat" });
    expect(within(firstRow).getByRole("combobox", { name: /^Priority for / })).toHaveTextContent("Normal");
    expect(within(firstRow).getByLabelText("5h ceiling %")).toHaveValue(75);
    expect(within(firstRow).getByText("ChatGPT")).toBeInTheDocument();
    const row = screen.getByRole("group", { name: "Second seat" });
    expect(within(row).getByText("Claude")).toBeInTheDocument();
    await selectOption(user, row, "Priority", "Use last");
    await selectOption(user, row, "Limits", "Custom for this key");
    expect(within(row).getByLabelText("5h ceiling %")).toHaveValue(95);
    expect(within(row).getByLabelText("Weekly ceiling %")).toHaveAttribute("placeholder", "80");
    expect(within(row).getByLabelText("5h pace margin %")).toHaveValue(0);
    await user.clear(within(row).getByLabelText("5h ceiling %"));
    await user.type(within(row).getByLabelText("5h ceiling %"), "85.5");
    await user.clear(within(row).getByLabelText("Weekly ceiling %"));
    await user.click(screen.getByRole("button", { name: "Save" }));

    await waitFor(() => expect(received).toEqual([{ rules: expectedRules }]));
    await waitFor(() => expect(screen.queryByRole("dialog", { name: "Account routing" })).not.toBeInTheDocument());
  });

  it("shows inline errors for invalid gates and ignores them after returning to inherited limits", async () => {
    const user = userEvent.setup();
    mockAccounts([first]);
    const { onSubmit } = renderDialog();
    const row = await screen.findByRole("group", { name: "Shared seat" });
    expect(within(row).getByRole("combobox", { name: /^Priority for / })).toHaveTextContent("Inherit (Use first)");
    expect(within(row).queryByLabelText("5h ceiling %")).not.toBeInTheDocument();
    await selectOption(user, row, "Limits", "Custom for this key");
    const ceiling = within(row).getByLabelText("5h ceiling %");
    await user.clear(ceiling);
    await user.type(ceiling, "0");
    expect(ceiling).toHaveAttribute("aria-invalid", "true");
    expect(within(row).getByText("Enter a number greater than 0 and at most 100.")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Save" })).toBeDisabled();
    await user.click(screen.getByRole("button", { name: "Save" }));
    expect(onSubmit).not.toHaveBeenCalled();
    await user.clear(ceiling);
    await user.type(ceiling, "100");
    const margin = within(row).getByLabelText("Weekly pace margin %");
    expect(margin).toHaveAttribute("placeholder", "off");
    await user.type(margin, "101");
    expect(within(row).getByText("Enter a number from 0 to 100.")).toBeInTheDocument();
    const window = within(row).getByLabelText("Pre-reset window min");
    await user.type(window, "1.5");
    expect(within(row).getByText("Enter a whole number of 0 or more.")).toBeInTheDocument();
    await selectOption(user, row, "Limits", "Inherit account limits");
    expect(screen.getByRole("button", { name: "Save" })).toBeEnabled();
    await user.click(screen.getByRole("button", { name: "Save" }));
    expect(onSubmit).toHaveBeenCalledExactlyOnceWith({ rules: [] });
  });

  it("discards edits on cancel and initializes from the latest rules on reopening", async () => {
    const user = userEvent.setup();
    mockAccounts([first]);
    const { props, onSubmit, onOpenChange, rerender } = renderDialog(createApiKey({ accountRoutingRules: [existingRule] }));
    const row = await screen.findByRole("group", { name: "Shared seat" });
    await user.clear(within(row).getByLabelText("5h ceiling %"));
    await user.type(within(row).getByLabelText("5h ceiling %"), "20");
    await user.click(screen.getByRole("button", { name: "Cancel" }));
    expect(onSubmit).not.toHaveBeenCalled();
    expect(onOpenChange).toHaveBeenCalledWith(false);
    rerender(<AccountRoutingDialog {...props} open={false} />);
    rerender(<AccountRoutingDialog {...props} apiKey={{ ...props.apiKey, accountRoutingRules: [{ ...existingRule, usageCeilingPrimaryPct: 65 }] }} />);
    const reopened = await screen.findByRole("group", { name: "Shared seat" });
    expect(within(reopened).getByLabelText("5h ceiling %")).toHaveValue(65);
  });

  it.each([
    { scoped: true, assigned: ["second"], visible: ["Second seat"] },
    { scoped: true, assigned: [], visible: [] },
    { scoped: false, assigned: ["second"], visible: ["Shared seat", "Second seat"] },
  ])("lists the permitted accounts for scope=$scoped, assigned=$assigned", async ({ scoped, assigned, visible }) => {
    const user = userEvent.setup();
    mockAccounts();
    const { onSubmit } = renderDialog(createApiKey({
      accountAssignmentScopeEnabled: scoped, assignedAccountIds: assigned,
      accountRoutingRules: [existingRule, { ...existingRule, accountId: "missing" }],
    }));
    await screen.findByText(scoped ? "Showing this key’s assigned accounts." : "Showing all accounts.");
    expect(screen.queryAllByRole("group").map((row) => row.getAttribute("aria-label"))).toEqual(visible);
    if (visible.length === 0) expect(screen.getByText("No accounts available.")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Save" }));
    expect(onSubmit).toHaveBeenCalledExactlyOnceWith({ rules: scoped ? [] : [existingRule] });
  });

  it("keeps the form and surfaces a mutation failure, then allows retry", async () => {
    const user = userEvent.setup();
    mockAccounts([first]);
    const apiKey = createApiKey();
    const errorToast = vi.spyOn(toast, "error");
    server.use(http.put(`/api/api-keys/${apiKey.id}/account-routing-rules`, () =>
      HttpResponse.json({ error: { message: "Routing update failed", code: "server_error" } }, { status: 500 }),
    ));
    renderSection(apiKey);
    await openRouting(user);
    const row = await screen.findByRole("group", { name: "Shared seat" });
    await selectOption(user, row, "Priority", "Use last");
    await user.click(screen.getByRole("button", { name: "Save" }));
    await waitFor(() => expect(errorToast).toHaveBeenCalledWith("Routing update failed"));
    expect(screen.getByRole("dialog", { name: "Account routing" })).toBeInTheDocument();
    expect(within(row).getByRole("combobox", { name: /^Priority for / })).toHaveTextContent("Use last");
    server.use(http.put(`/api/api-keys/${apiKey.id}/account-routing-rules`, () => HttpResponse.json(apiKey)));
    await user.click(screen.getByRole("button", { name: "Save" }));
    await waitFor(() => expect(screen.queryByRole("dialog", { name: "Account routing" })).not.toBeInTheDocument());
    errorToast.mockRestore();
  });

  it("surfaces an account loading error and retries without enabling a destructive empty save", async () => {
    const user = userEvent.setup();
    server.use(http.get("/api/accounts", () => HttpResponse.json({ error: { message: "Accounts unavailable", code: "server_error" } }, { status: 500 })));
    renderDialog();
    expect(await screen.findByText("Accounts unavailable")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Save" })).not.toBeInTheDocument();
    mockAccounts([first]);
    await user.click(screen.getByRole("button", { name: "Retry" }));
    expect(await screen.findByRole("group", { name: "Shared seat" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Save" })).toBeEnabled();
  });

  it("uses display name or email and retains unknown provider names", async () => {
    mockAccounts([
      createAccountSummary({ accountId: "named", displayName: "Named seat", provider: "other" }),
      createAccountSummary({ accountId: "email", displayName: "", email: "seat@example.com", provider: "anthropic" }),
    ]);
    renderDialog();
    const named = await screen.findByRole("group", { name: "Named seat" });
    expect(within(named).getByText("other")).toBeInTheDocument();
    expect(screen.getByRole("group", { name: "seat@example.com" })).toBeInTheDocument();
  });

  it("preserves the draft after a background account refresh fails and blocks save until retry", async () => {
    const user = userEvent.setup();
    mockAccounts([first]);
    const { queryClient } = renderDialog();
    const row = await screen.findByRole("group", { name: "Shared seat" });
    await selectOption(user, row, "Priority", "Use last");
    server.use(http.get("/api/accounts", () => HttpResponse.json({ error: { message: "Refresh failed", code: "server_error" } }, { status: 500 })));
    await queryClient.invalidateQueries({ queryKey: ["accounts", "list"] });
    expect(await screen.findByText("Refresh failed")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Save" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Cancel" })).toBeEnabled();
    expect(within(row).getByRole("combobox", { name: /^Priority for / })).toHaveTextContent("Use last");
    mockAccounts([first]);
    await user.click(screen.getByRole("button", { name: "Retry" }));
    await waitFor(() => expect(screen.getByRole("button", { name: "Save" })).toBeEnabled());
    expect(within(row).getByRole("combobox", { name: /^Priority for / })).toHaveTextContent("Use last");
  });

  it("copies account limits again when custom limits are reselected", async () => {
    const user = userEvent.setup();
    mockAccounts([first]);
    renderDialog();
    const row = await screen.findByRole("group", { name: "Shared seat" });
    await selectOption(user, row, "Limits", "Custom for this key");
    await user.clear(within(row).getByLabelText("5h ceiling %"));
    await user.type(within(row).getByLabelText("5h ceiling %"), "70");
    await selectOption(user, row, "Limits", "Inherit account limits");
    await selectOption(user, row, "Limits", "Custom for this key");
    expect(within(row).getByLabelText("5h ceiling %")).toHaveValue(90);
  });

  it("disables controls and dismissal while saving", async () => {
    const user = userEvent.setup();
    mockAccounts([first]);
    const { props, rerender, onOpenChange } = renderDialog();
    await screen.findByRole("group", { name: "Shared seat" });
    rerender(<AccountRoutingDialog {...props} busy />);
    expect(screen.getByRole("button", { name: "Saving..." })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Cancel" })).toBeDisabled();
    expect(screen.getByRole("combobox", { name: /^Priority for / })).toBeDisabled();
    await user.keyboard("{Escape}");
    expect(onOpenChange).not.toHaveBeenCalled();
  });
});

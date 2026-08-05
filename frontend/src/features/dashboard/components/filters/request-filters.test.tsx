import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { RequestFilters } from "@/features/dashboard/components/filters/request-filters";
import type { FilterState } from "@/features/dashboard/schemas";

const FILTERS: FilterState = {
  search: "",
  timeframe: "all",
  accountIds: [],
  apiKeyIds: [],
  providers: [],
  modelOptions: [],
  statuses: [],
  limit: 50,
  offset: 0,
};

function renderFilters(providerOptions: { value: string; label: string }[], filters = FILTERS) {
  const onProviderChange = vi.fn();
  render(
    <RequestFilters
      filters={filters}
      accountOptions={[]}
      apiKeyOptions={[]}
      providerOptions={providerOptions}
      modelOptions={[]}
      statusOptions={[]}
      onSearchChange={vi.fn()}
      onTimeframeChange={vi.fn()}
      onAccountChange={vi.fn()}
      onApiKeyChange={vi.fn()}
      onProviderChange={onProviderChange}
      onModelChange={vi.fn()}
      onStatusChange={vi.fn()}
      onReset={vi.fn()}
    />,
  );
  return { onProviderChange };
}

describe("RequestFilters provider control", () => {
  it("stays hidden when only one provider has traffic", () => {
    renderFilters([{ value: "openai", label: "Codex" }]);

    expect(screen.queryByRole("button", { name: /providers/i })).not.toBeInTheDocument();
  });

  it("stays hidden when no provider has traffic", () => {
    renderFilters([]);

    expect(screen.queryByRole("button", { name: /providers/i })).not.toBeInTheDocument();
  });

  it("appears once a second provider serves traffic", () => {
    renderFilters([
      { value: "openai", label: "Codex" },
      { value: "anthropic", label: "Claude" },
    ]);

    expect(screen.getByRole("button", { name: /providers/i })).toBeInTheDocument();
  });

  it("reports the selected provider", async () => {
    const user = userEvent.setup();
    const { onProviderChange } = renderFilters([
      { value: "openai", label: "Codex" },
      { value: "anthropic", label: "Claude" },
    ]);

    await user.click(screen.getByRole("button", { name: /providers/i }));
    await user.click(await screen.findByRole("menuitemcheckbox", { name: "Claude" }));

    expect(onProviderChange).toHaveBeenCalledWith(["anthropic"]);
  });
});

import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { ProviderScopeControl } from "@/features/providers/components/provider-scope-control";

describe("ProviderScopeControl", () => {
  it("renders all providers as a segmented radio control", async () => {
    const user = userEvent.setup();
    const onChange = vi.fn();
    render(<ProviderScopeControl value="all" onChange={onChange} />);

    expect(screen.getByRole("radio", { name: "All" })).toHaveAttribute("aria-checked", "true");
    await user.click(screen.getByRole("radio", { name: "Claude" }));
    expect(onChange).toHaveBeenCalledWith("anthropic");
  });

  it("supports roving focus and arrow-key selection", async () => {
    const user = userEvent.setup();
    const onChange = vi.fn();
    render(<ProviderScopeControl value="all" onChange={onChange} />);

    const all = screen.getByRole("radio", { name: "All" });
    const openai = screen.getByRole("radio", { name: "OpenAI" });
    expect(all).toHaveAttribute("tabindex", "0");
    expect(openai).toHaveAttribute("tabindex", "-1");

    all.focus();
    await user.keyboard("{ArrowRight}");

    expect(onChange).toHaveBeenCalledWith("openai");
    expect(openai).toHaveFocus();
  });
});

import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { AnthropicApiKeyDialog } from "@/features/accounts/components/anthropic-api-key-dialog";

describe("AnthropicApiKeyDialog", () => {
  it("submits a trimmed Console API key without displaying it as plain text", async () => {
    const user = userEvent.setup();
    const onSubmit = vi.fn().mockResolvedValue(undefined);
    const onOpenChange = vi.fn();
    render(
      <AnthropicApiKeyDialog
        open
        mode="create"
        busy={false}
        onOpenChange={onOpenChange}
        onSubmit={onSubmit}
      />,
    );

    await user.type(screen.getByLabelText("Label"), " Production Claude ");
    const secretInput = screen.getByLabelText("Anthropic API key");
    await user.type(secretInput, " sk-ant-api03-secret ");
    expect(secretInput).toHaveAttribute("type", "password");
    await user.click(screen.getByRole("button", { name: "Add key" }));

    expect(onSubmit).toHaveBeenCalledWith({
      label: "Production Claude",
      apiKey: "sk-ant-api03-secret",
    });
    expect(onOpenChange).toHaveBeenCalledWith(false);
  });

  it("requires both fields", async () => {
    const user = userEvent.setup();
    const onSubmit = vi.fn();
    render(
      <AnthropicApiKeyDialog
        open
        mode="replace"
        busy={false}
        onOpenChange={vi.fn()}
        onSubmit={onSubmit}
      />,
    );

    await user.click(screen.getByRole("button", { name: "Replace key" }));
    expect(screen.getByRole("alert")).toHaveTextContent("Enter a label");
    expect(onSubmit).not.toHaveBeenCalled();
  });
});

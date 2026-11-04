import { fireEvent, render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { UsageCeilingFields } from "@/features/accounts/components/usage-ceiling-fields";
import { createAccountSummary } from "@/test/mocks/factories";

describe("UsageCeilingFields", () => {
  it.each([
    ["5h ceiling", "usageCeilingPrimaryPct"],
    ["Weekly ceiling", "usageCeilingSecondaryPct"],
  ] as const)("commits only %s on blur", async (label, key) => {
    const user = userEvent.setup();
    const onChange = vi.fn();
    const account = createAccountSummary();
    render(<UsageCeilingFields account={account} busy={false} onChange={onChange} />);

    await user.type(screen.getByRole("spinbutton", { name: label }), "85");
    expect(onChange).not.toHaveBeenCalled();
    await user.tab();

    expect(onChange).toHaveBeenCalledExactlyOnceWith(account.accountId, { [key]: 85 });
  });

  it("clears a stored ceiling on blur", async () => {
    const user = userEvent.setup();
    const onChange = vi.fn();
    const account = createAccountSummary({ usageCeilingPrimaryPct: 80 });
    render(<UsageCeilingFields account={account} busy={false} onChange={onChange} />);

    await user.clear(screen.getByRole("spinbutton", { name: "5h ceiling" }));
    await user.tab();

    expect(onChange).toHaveBeenCalledExactlyOnceWith(account.accountId, {
      usageCeilingPrimaryPct: null,
    });
  });

  it.each(["0", "101", "-1"])("reverts invalid ceiling %s", async (value) => {
    const user = userEvent.setup();
    const onChange = vi.fn();
    render(
      <UsageCeilingFields
        account={createAccountSummary({ usageCeilingPrimaryPct: 80 })}
        busy={false}
        onChange={onChange}
      />,
    );
    const input = screen.getByRole("spinbutton", { name: "5h ceiling" });
    await user.clear(input);
    await user.type(input, value);
    await user.tab();

    expect(input).toHaveValue(80);
    expect(onChange).not.toHaveBeenCalled();
  });

  it.each([
    ["80", 80],
    ["90", 90],
    ["95", 95],
    ["Off", null],
  ] as const)("commits the %s preset immediately", async (label, value) => {
    const user = userEvent.setup();
    const onChange = vi.fn();
    const account = createAccountSummary({ usageCeilingPrimaryPct: 85 });
    render(<UsageCeilingFields account={account} busy={false} onChange={onChange} />);

    await user.click(within(screen.getByRole("group", { name: "5h ceiling presets" }))
      .getByRole("button", { name: label }));

    expect(onChange).toHaveBeenCalledExactlyOnceWith(account.accountId, {
      usageCeilingPrimaryPct: value,
    });
  });

  it("does not save the active preset", async () => {
    const user = userEvent.setup();
    const onChange = vi.fn();
    render(
      <UsageCeilingFields
        account={createAccountSummary({ usageCeilingPrimaryPct: 90 })}
        busy={false}
        onChange={onChange}
      />,
    );
    const preset = within(screen.getByRole("group", { name: "5h ceiling presets" }))
      .getByRole("button", { name: "90" });

    expect(preset).toHaveAttribute("aria-pressed", "true");
    await user.click(preset);
    expect(onChange).not.toHaveBeenCalled();
  });

  it("reverts browser-reported non-numeric input instead of clearing the ceiling", () => {
    const onChange = vi.fn();
    render(
      <UsageCeilingFields
        account={createAccountSummary({ usageCeilingPrimaryPct: 80 })}
        busy={false}
        onChange={onChange}
      />,
    );
    const input = screen.getByRole<HTMLInputElement>("spinbutton", { name: "5h ceiling" });
    const validity = input.validity;
    const validitySpy = vi.spyOn(input, "validity", "get")
      .mockReturnValue({ ...validity, badInput: true });

    fireEvent.change(input, { target: { value: "" } });
    fireEvent.blur(input);

    expect(input).toHaveValue(80);
    expect(onChange).not.toHaveBeenCalled();
    validitySpy.mockRestore();
  });

  it("commits decimal ceilings with Enter and leaves unchanged values alone", async () => {
    const user = userEvent.setup();
    const onChange = vi.fn();
    const account = createAccountSummary({ usageCeilingPrimaryPct: 80 });
    render(<UsageCeilingFields account={account} busy={false} onChange={onChange} />);
    const input = screen.getByRole("spinbutton", { name: "5h ceiling" });
    await user.click(input);
    await user.tab();
    expect(onChange).not.toHaveBeenCalled();

    await user.clear(input);
    await user.type(input, "85.5{Enter}");
    expect(onChange).toHaveBeenCalledExactlyOnceWith(account.accountId, {
      usageCeilingPrimaryPct: 85.5,
    });
  });

  it.each([
    { busy: false, readOnly: true },
    { busy: true, readOnly: false },
  ])("disables inputs and presets when %j", async (state) => {
    const user = userEvent.setup();
    const onChange = vi.fn();
    render(<UsageCeilingFields account={createAccountSummary()} {...state} onChange={onChange} />);

    for (const input of screen.getAllByRole("spinbutton")) {
      expect(input).toBeDisabled();
    }
    for (const button of screen.getAllByRole("button")) {
      expect(button).toBeDisabled();
      await user.click(button);
    }
    expect(onChange).not.toHaveBeenCalled();
  });

  it("reseeds from updated account values", () => {
    const account = createAccountSummary({ usageCeilingPrimaryPct: 80 });
    const onChange = vi.fn();
    const { rerender } = render(
      <UsageCeilingFields account={account} busy={false} onChange={onChange} />,
    );

    rerender(<UsageCeilingFields account={{ ...account, usageCeilingPrimaryPct: 95 }} busy={false} onChange={onChange} />);
    expect(screen.getByRole("spinbutton", { name: "5h ceiling" })).toHaveValue(95);
    expect(within(screen.getByRole("group", { name: "5h ceiling presets" }))
      .getByRole("button", { name: "95" })).toHaveAttribute("aria-pressed", "true");
    expect(onChange).not.toHaveBeenCalled();
  });

  it("uses a preset without also committing an unfinished draft", async () => {
    const user = userEvent.setup();
    const onChange = vi.fn();
    const account = createAccountSummary();
    render(<UsageCeilingFields account={account} busy={false} onChange={onChange} />);
    await user.type(screen.getByRole("spinbutton", { name: "5h ceiling" }), "85");
    await user.click(within(screen.getByRole("group", { name: "5h ceiling presets" }))
      .getByRole("button", { name: "90" }));

    expect(onChange).toHaveBeenCalledExactlyOnceWith(account.accountId, {
      usageCeilingPrimaryPct: 90,
    });
  });
});

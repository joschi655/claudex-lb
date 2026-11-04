import { act, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import { UsageCeilingBadge, UsageCeilingMarker } from "@/components/usage-ceiling-marker";

describe("UsageCeilingMarker", () => {
  it("marks the remaining quota threshold with a hidden, named line", () => {
    render(<UsageCeilingMarker label="5h" ceilingPct={90} />);

    const marker = screen.getByTestId("usage-ceiling-marker");
    expect(marker).toHaveStyle({ left: "10%" });
    expect(marker).toHaveAttribute("aria-hidden", "true");
    expect(marker).toHaveAttribute("title", "5h ceiling at 90% used");
  });

  it.each([null, undefined, 0, 101])("omits the marker for ceiling %s", (ceilingPct) => {
    render(<UsageCeilingMarker label="Weekly" ceilingPct={ceilingPct} />);

    expect(screen.queryByTestId("usage-ceiling-marker")).not.toBeInTheDocument();
  });
});

describe("UsageCeilingBadge", () => {
  afterEach(() => {
    vi.useRealTimers();
  });

  it("clears the badge when its window resets without new usage data", () => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date("2026-01-01T12:00:00Z"));
    render(
      <UsageCeilingBadge
        label="5h"
        ceilingPct={90}
        remainingPercent={5}
        resetAt="2026-01-01T12:00:01Z"
      />,
    );

    expect(screen.getByText("At ceiling")).toBeInTheDocument();

    act(() => vi.advanceTimersByTime(1000));

    expect(screen.queryByText("At ceiling")).not.toBeInTheDocument();
  });

  it("opens a tooltip explaining the window's ceiling", async () => {
    const user = userEvent.setup();
    render(<UsageCeilingBadge label="Weekly" ceilingPct={90} remainingPercent={5} />);

    const description = "Weekly usage reached this account's 90% ceiling. It is skipped until the window resets.";
    const badge = screen.getByText("At ceiling");
    expect(badge).toHaveAttribute("title", description);
    expect(badge).toHaveAttribute("aria-label", description);

    await user.hover(badge);

    expect(await screen.findByRole("tooltip")).toHaveTextContent(description);
  });
});

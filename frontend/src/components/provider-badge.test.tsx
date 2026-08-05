import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { ProviderBadge } from "@/components/provider-badge";
import { formatProviderLabel } from "@/utils/formatters";

describe("ProviderBadge", () => {
  it("marks Claude rows", () => {
    render(<ProviderBadge provider="anthropic" />);

    expect(screen.getByText("Claude")).toBeInTheDocument();
  });

  it("leaves Codex rows unmarked so single-provider deployments look unchanged", () => {
    const { container } = render(<ProviderBadge provider="openai" />);

    expect(container).toBeEmptyDOMElement();
  });

  it("renders nothing without a provider", () => {
    const { container } = render(<ProviderBadge provider={null} />);

    expect(container).toBeEmptyDOMElement();
  });
});

describe("formatProviderLabel", () => {
  it("names the known providers", () => {
    expect(formatProviderLabel("anthropic")).toBe("Claude");
    expect(formatProviderLabel("openai")).toBe("Codex");
  });

  it("falls back to the raw value for anything else", () => {
    expect(formatProviderLabel("future-provider")).toBe("future-provider");
  });
});

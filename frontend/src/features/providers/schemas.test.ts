import { describe, expect, it } from "vitest";

import { parseProviderScope, ProviderScopeSchema } from "@/features/providers/schemas";

describe("provider scopes", () => {
  it("accepts supported scopes and defaults invalid URL values to all", () => {
    expect(ProviderScopeSchema.parse("anthropic")).toBe("anthropic");
    expect(parseProviderScope("openai")).toBe("openai");
    expect(parseProviderScope("unknown")).toBe("all");
    expect(parseProviderScope(null)).toBe("all");
  });
});

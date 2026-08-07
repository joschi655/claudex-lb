import { describe, expect, it } from "vitest";

import { servingAccountIds } from "@/features/accounts/serving";
import type { AccountSummary } from "@/features/accounts/schemas";

function account(
  accountId: string,
  provider: string,
  lastServedAt: string | null,
): AccountSummary {
  return {
    accountId,
    provider,
    email: `${accountId}@example.com`,
    displayName: accountId,
    planType: "plus",
    status: "active",
    lastServedAt,
  } as AccountSummary;
}

describe("servingAccountIds", () => {
  it("names the newest request per provider", () => {
    const serving = servingAccountIds([
      account("claude-a", "anthropic", "2026-08-07T12:00:00Z"),
      account("claude-b", "anthropic", "2026-08-07T12:05:00Z"),
      account("codex-a", "openai", "2026-08-07T11:00:00Z"),
    ]);

    expect(serving).toEqual(new Set(["claude-b", "codex-a"]));
  });

  it("lets each provider name its own account", () => {
    // A busy Claude pool must not speak for an idle-but-serving Codex one.
    const serving = servingAccountIds([
      account("claude", "anthropic", "2026-08-07T12:59:00Z"),
      account("codex", "openai", "2026-08-07T12:01:00Z"),
    ]);

    expect(serving.has("claude")).toBe(true);
    expect(serving.has("codex")).toBe(true);
  });

  it("names nobody when the pool is idle", () => {
    // The server only reports activity inside its recent window, so an idle
    // pool arrives as all-null rather than as stale timestamps.
    expect(
      servingAccountIds([
        account("a", "anthropic", null),
        account("b", "anthropic", null),
      ]),
    ).toEqual(new Set());
  });

  it("ignores an unparseable timestamp rather than crowning it", () => {
    const serving = servingAccountIds([
      account("good", "anthropic", "2026-08-07T12:00:00Z"),
      account("bad", "anthropic", "not-a-date"),
    ]);

    expect(serving).toEqual(new Set(["good"]));
  });

  it("handles an empty pool", () => {
    expect(servingAccountIds([])).toEqual(new Set());
  });
});

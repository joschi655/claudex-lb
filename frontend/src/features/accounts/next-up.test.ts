import { describe, expect, it } from "vitest";

import { nextUpMarks } from "@/features/accounts/next-up";
import type { NextAccountsResponse } from "@/features/accounts/schemas";

function response(
  ...entries: NextAccountsResponse["nextUp"]
): NextAccountsResponse {
  return { nextUp: entries };
}

describe("nextUpMarks", () => {
  it("marks the account each provider named", () => {
    const marks = nextUpMarks(
      response(
        { provider: "anthropic", accountId: "claude-b", certain: true },
        { provider: "openai", accountId: "codex-a", certain: true },
      ),
    );

    expect([...marks.keys()]).toEqual(["claude-b", "codex-a"]);
  });

  it("carries the uncertainty through", () => {
    // The default strategy draws at random among weighted candidates, so the
    // named account is a front-runner and the badge has to say so.
    const marks = nextUpMarks(
      response({ provider: "anthropic", accountId: "claude-a", certain: false }),
    );

    expect(marks.get("claude-a")).toEqual({ certain: false });
  });

  it("marks nobody for a provider with nothing eligible", () => {
    const marks = nextUpMarks(
      response({
        provider: "anthropic",
        accountId: null,
        certain: true,
        errorMessage: "No accounts available",
      }),
    );

    expect(marks.size).toBe(0);
  });

  it("marks an account even though the pool is idle", () => {
    // The whole point of the change: "next" is answerable with no traffic at
    // all, where a last-served view would name nobody.
    const marks = nextUpMarks(
      response({ provider: "anthropic", accountId: "claude-a", certain: true }),
    );

    expect(marks.has("claude-a")).toBe(true);
  });

  it("handles a response that has not arrived yet", () => {
    expect(nextUpMarks(undefined)).toEqual(new Map());
  });
});

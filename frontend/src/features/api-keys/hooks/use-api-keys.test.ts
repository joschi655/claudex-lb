import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { renderHook, waitFor } from "@testing-library/react";
import { createElement, type PropsWithChildren } from "react";
import { http, HttpResponse } from "msw";
import { toast } from "sonner";
import { afterEach, describe, expect, it, vi } from "vitest";

import { useApiKeys } from "@/features/api-keys/hooks/use-api-keys";
import type { ApiKeyAccountRoutingRule } from "@/features/api-keys/schemas";
import { server } from "@/test/mocks/server";

function createTestQueryClient(): QueryClient {
  return new QueryClient({
    defaultOptions: {
      queries: {
        retry: false,
        gcTime: 0,
      },
    },
  });
}

function createWrapper(queryClient: QueryClient) {
  return function Wrapper({ children }: PropsWithChildren) {
    return createElement(QueryClientProvider, { client: queryClient }, children);
  };
}

describe("useApiKeys", () => {
  afterEach(() => vi.restoreAllMocks());

  it("replaces account routing rules with PUT and refetches the key list", async () => {
    const successToast = vi.spyOn(toast, "success");
    const queryClient = createTestQueryClient();
    const invalidateSpy = vi.spyOn(queryClient, "invalidateQueries");
    const requests: { method: string; url: string; body: unknown }[] = [];
    server.events.on("request:start", async ({ request }) => {
      if (request.method === "PUT") {
        requests.push({ method: request.method, url: request.url, body: await request.clone().json() });
      }
    });
    const { result } = renderHook(() => useApiKeys(), {
      wrapper: createWrapper(queryClient),
    });
    await waitFor(() => expect(result.current.apiKeysQuery.isSuccess).toBe(true));
    const key = result.current.apiKeysQuery.data?.[0];
    if (!key) throw new Error("Expected an API key");
    const rule: ApiKeyAccountRoutingRule = {
      accountId: "acc_primary",
      routingPolicy: "preserve",
      overrideGates: true,
      usageCeilingPrimaryPct: 90,
      usageCeilingSecondaryPct: null,
      paceMarginPrimaryPct: 0,
      paceMarginSecondaryPct: null,
      preResetWindowMinutes: null,
    };

    try {
      const updated = await result.current.accountRoutingRulesMutation.mutateAsync({
        keyId: key.id,
        payload: { rules: [rule] },
      });
      expect(updated.accountRoutingRules).toEqual([rule]);
      expect(requests).toEqual([{
        method: "PUT",
        url: `${window.location.origin}/api/api-keys/${encodeURIComponent(key.id)}/account-routing-rules`,
        body: { rules: [rule] },
      }]);
      expect(invalidateSpy).toHaveBeenCalledWith({ queryKey: ["api-keys", "list"] });
      await waitFor(() => {
        expect(result.current.apiKeysQuery.data?.find((item) => item.id === key.id)?.accountRoutingRules)
          .toEqual([rule]);
      });
      expect(successToast).toHaveBeenCalledWith("Account routing rules updated");
      await result.current.accountRoutingRulesMutation.mutateAsync({
        keyId: key.id,
        payload: { rules: [] },
      });
      await waitFor(() => {
        expect(result.current.apiKeysQuery.data?.find((item) => item.id === key.id)?.accountRoutingRules)
          .toEqual([]);
      });
    } finally {
      server.events.removeAllListeners("request:start");
    }
  });

  it("surfaces routing rule save errors", async () => {
    const errorToast = vi.spyOn(toast, "error");
    server.use(http.put("/api/api-keys/:keyId/account-routing-rules", () =>
      HttpResponse.json({ error: { code: "save_failed", message: "Could not save rules" } }, { status: 500 }),
    ));
    const { result } = renderHook(() => useApiKeys(), {
      wrapper: createWrapper(createTestQueryClient()),
    });

    await expect(result.current.accountRoutingRulesMutation.mutateAsync({
      keyId: "key_1", payload: { rules: [] },
    })).rejects.toThrow("Could not save rules");
    expect(errorToast).toHaveBeenCalledWith("Could not save rules");
  });

  it("runs CRUD mutations and returns plain key on create", async () => {
    const queryClient = createTestQueryClient();
    const invalidateSpy = vi.spyOn(queryClient, "invalidateQueries");

    const { result } = renderHook(() => useApiKeys(), {
      wrapper: createWrapper(queryClient),
    });

    await waitFor(() => expect(result.current.apiKeysQuery.isSuccess).toBe(true));
    const existingKeyId = result.current.apiKeysQuery.data?.[0]?.id;
    expect(existingKeyId).toBeTruthy();
    if (!existingKeyId) throw new Error("Expected at least one API key in test data");

    const created = await result.current.createMutation.mutateAsync({
      name: "Test Key",
      allowedModels: ["gpt-5.1"],
      applyToCodexModel: true,
      weeklyTokenLimit: 1000,
      expiresAt: null,
    });
    expect(created.key).toContain("sk-test");

    await result.current.updateMutation.mutateAsync({
      keyId: existingKeyId,
      payload: {
        name: "Updated Name",
      },
    });

    await result.current.regenerateMutation.mutateAsync(existingKeyId);
    await result.current.deleteMutation.mutateAsync(created.id);

    await waitFor(() => {
      expect(invalidateSpy).toHaveBeenCalledWith({ queryKey: ["api-keys", "list"] });
    });
  });
});

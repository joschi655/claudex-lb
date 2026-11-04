import { describe, expect, it } from "vitest";

import { listAccounts, updateAccountPaceGates } from "@/features/accounts/api";
import { listApiKeys, replaceApiKeyAccountRoutingRules } from "@/features/api-keys/api";
import type { ApiKeyAccountRoutingRule } from "@/features/api-keys/schemas";
import { handlers } from "@/test/mocks/handlers";

/**
 * Structural test that ensures the MSW handler set covers every API endpoint
 * consumed by the frontend. When a new endpoint is added to an api.ts file,
 * add the corresponding method+path here so this test forces the mock handler
 * to be created at the same time.
 */

function extractHandlerPaths(): string[] {
	return handlers.map((handler) => {
		const { method, path } = handler.info;
		// Normalize: MSW stores method in uppercase, path as the string literal
		return `${String(method).toUpperCase()} ${String(path)}`;
	});
}

// All API endpoints consumed by the frontend (method + MSW path pattern).
// Parameterized segments use MSW `:param` syntax.
const EXPECTED_ENDPOINTS = [
	// health
	"GET /health",
	// runtime
	"GET /api/runtime/version",
	// dashboard
	"GET /api/dashboard/overview",
	"GET /api/dashboard/projections",
	"GET /api/request-logs",
	"GET /api/request-logs/options",
	// accounts
	"GET /api/accounts",
	"GET /api/accounts/next-up",
	"POST /api/accounts/import",
	"PATCH /api/accounts/:accountId",
	"POST /api/accounts/:accountId/pause",
	"POST /api/accounts/:accountId/reactivate",
	"POST /api/accounts/:accountId/probe",
	"PUT /api/accounts/:accountId/alias",
	"PUT /api/accounts/:accountId/limit-warmup",
	"PUT /api/accounts/:accountId/routing-policy",
	"PUT /api/accounts/:accountId/pin",
	"PUT /api/accounts/:accountId/pace-gates",
	"GET /api/accounts/:accountId/trends",
	"GET /api/accounts/:accountId/usage-reset-credits",
	"POST /api/accounts/:accountId/usage-reset-credits/consume",
	"POST /api/accounts/:accountId/export",
	"POST /api/accounts/:accountId/export/auth",
	"DELETE /api/accounts/:accountId",
	// oauth
	"POST /api/oauth/start",
	"GET /api/oauth/status",
	"POST /api/oauth/complete",
	// auth
	"GET /api/dashboard-auth/session",
	"POST /api/dashboard-auth/password/setup",
	"POST /api/dashboard-auth/password/login",
	"POST /api/dashboard-auth/guest/login",
	"POST /api/dashboard-auth/password/change",
	"POST /api/dashboard-auth/guest/password",
	"DELETE /api/dashboard-auth/guest/password",
	"DELETE /api/dashboard-auth/password",
	"POST /api/dashboard-auth/totp/setup/start",
	"POST /api/dashboard-auth/totp/setup/confirm",
	"POST /api/dashboard-auth/totp/verify",
	"POST /api/dashboard-auth/totp/disable",
	"POST /api/dashboard-auth/logout",
	// settings
	"GET /api/settings",
	"PUT /api/settings",
	"GET /api/settings/upstream-proxy",
	"POST /api/settings/upstream-proxy/endpoints",
	"POST /api/settings/upstream-proxy/endpoints/:endpointId/test",
	"POST /api/settings/upstream-proxy/pools",
	"POST /api/settings/upstream-proxy/pools/:poolId/members",
	"PUT /api/settings/upstream-proxy/accounts/:accountId/binding",
	"GET /api/sticky-sessions",
	"POST /api/sticky-sessions/delete",
	"POST /api/sticky-sessions/delete-filtered",
	"POST /api/sticky-sessions/purge",
	// quota planner
	"GET /api/quota-planner/settings",
	"PUT /api/quota-planner/settings",
	"GET /api/quota-planner/decisions",
	"GET /api/quota-planner/forecast",
	"POST /api/quota-planner/warm-now",
	"POST /api/quota-planner/decisions/:decisionId/cancel",
	// firewall
	"GET /api/firewall/ips",
	"POST /api/firewall/ips",
	"DELETE /api/firewall/ips/:ipAddress",
	// models
	"GET /api/models",
	"GET /api/model-sources/",
	"POST /api/model-sources/",
	"PATCH /api/model-sources/:sourceId",
	"DELETE /api/model-sources/:sourceId",
	// api-keys
	"GET /api/api-keys/",
	"POST /api/api-keys/",
	"PATCH /api/api-keys/:keyId",
	"PUT /api/api-keys/:keyId/account-routing-rules",
	"DELETE /api/api-keys/:keyId",
	"POST /api/api-keys/:keyId/regenerate",
	"GET /api/api-keys/:keyId/trends",
	"GET /api/api-keys/:keyId/usage-7d",
	// automations
	"GET /api/automations",
	"GET /api/automations/options",
	"GET /api/automations/runs",
	"GET /api/automations/runs/options",
	"GET /api/automations/runs/:runId/details",
	"POST /api/automations",
	"PATCH /api/automations/:automationId",
	"DELETE /api/automations/:automationId",
	"POST /api/automations/:automationId/run-now",
	"GET /api/automations/:automationId/runs",
];

describe("MSW handler coverage", () => {
	it("covers all expected API endpoints", () => {
		const actual = new Set(extractHandlerPaths());
		const missing = EXPECTED_ENDPOINTS.filter((ep) => !actual.has(ep));
		expect(missing, "Missing MSW handlers for these endpoints").toEqual([]);
	});

	it("has no unexpected handlers outside the expected set", () => {
		const expected = new Set(EXPECTED_ENDPOINTS);
		const actual = extractHandlerPaths();
		const extra = actual.filter((ep) => !expected.has(ep));
		expect(
			extra,
			"Unexpected MSW handlers — add them to EXPECTED_ENDPOINTS",
		).toEqual([]);
	});
});


describe("account limit and routing rule handlers", () => {
  const rule: ApiKeyAccountRoutingRule = {
    accountId: "acc_primary",
    routingPolicy: "preserve",
    overrideGates: true,
    usageCeilingPrimaryPct: 90,
    usageCeilingSecondaryPct: 95,
    paceMarginPrimaryPct: 0,
    paceMarginSecondaryPct: 10,
    preResetWindowMinutes: 30,
  };

  it("persists ceilings, preserves omitted fields, and clears explicit nulls", async () => {
    await updateAccountPaceGates("acc_primary", {
      usageCeilingPrimaryPct: 85,
      usageCeilingSecondaryPct: 95,
      paceMarginPrimaryPct: 0,
    });
    const updated = await updateAccountPaceGates("acc_primary", {
      usageCeilingPrimaryPct: null,
    });
    expect(updated).toMatchObject({
      usageCeilingPrimaryPct: null,
      usageCeilingSecondaryPct: 95,
      paceMarginPrimaryPct: 0,
    });
    const accounts = await listAccounts();
    expect(accounts.accounts.find((account) => account.accountId === "acc_primary"))
      .toMatchObject({
        usageCeilingPrimaryPct: null,
        usageCeilingSecondaryPct: 95,
        paceMarginPrimaryPct: 0,
      });
  });

  it("drops fully inherited rules and clears gates for policy-only rules", async () => {
    const keys = await listApiKeys();
    const key = keys[0];
    const updated = await replaceApiKeyAccountRoutingRules(key.id, {
      rules: [
        { ...rule, overrideGates: false },
        { ...rule, accountId: "acc_secondary", routingPolicy: null, overrideGates: false },
        { ...rule, accountId: "acc_other", routingPolicy: null },
      ],
    });
    expect(updated.assignedAccountIds).toEqual(key.assignedAccountIds);
    expect(updated.accountRoutingRules).toEqual([
      {
        ...rule,
        overrideGates: false,
        usageCeilingPrimaryPct: null,
        usageCeilingSecondaryPct: null,
        paceMarginPrimaryPct: null,
        paceMarginSecondaryPct: null,
        preResetWindowMinutes: null,
      },
      { ...rule, accountId: "acc_other", routingPolicy: null },
    ]);
    expect((await listApiKeys())[0].accountRoutingRules).toEqual(updated.accountRoutingRules);
    const cleared = await replaceApiKeyAccountRoutingRules(key.id, { rules: [] });
    expect(cleared.accountRoutingRules).toEqual([]);
  });

  it.each([
    "/api/accounts/missing/pace-gates",
    "/api/api-keys/missing/account-routing-rules",
  ])("returns 404 for missing resources at %s", async (path) => {
    const response = await fetch(path, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ rules: [] }),
    });
    expect(response.status).toBe(404);
  });

  it.each([
    ["/api/accounts/acc_primary/pace-gates", { usageCeilingPrimaryPct: 0 }],
    ["/api/api-keys/key_1/account-routing-rules", { rules: [{ ...rule, usageCeilingSecondaryPct: 0 }] }],
  ])("returns 422 for invalid limits at %s", async (path, body) => {
    const response = await fetch(path, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    expect(response.status).toBe(422);
  });
});

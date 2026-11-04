import { describe, expect, it } from "vitest";

import type { ApiKeyAccountRoutingRule } from "@/features/api-keys/schemas";
import { createAccountSummary } from "@/test/mocks/factories";

import {
  accountRoutingRowsToRules,
  accountRoutingRulesToRows,
  ROUTING_GATE_FIELDS,
  validateRoutingGate,
} from "./account-routing-utils";

const nullGates = {
  usageCeilingPrimaryPct: null,
  usageCeilingSecondaryPct: null,
  paceMarginPrimaryPct: null,
  paceMarginSecondaryPct: null,
  preResetWindowMinutes: null,
};

describe("account routing conversions", () => {
  const account = createAccountSummary({
    usageCeilingPrimaryPct: 90,
    paceMarginPrimaryPct: 0,
    preResetWindowMinutes: 15,
  });

  it("initializes inherited rows from account gates and omits them on save", () => {
    const rows = accountRoutingRulesToRows([account], []);
    expect(rows).toEqual([{
      accountId: account.accountId,
      routingPolicy: "inherit",
      overrideGates: false,
      usageCeilingPrimaryPct: "90",
      usageCeilingSecondaryPct: "",
      paceMarginPrimaryPct: "0",
      paceMarginSecondaryPct: "",
      preResetWindowMinutes: "15",
    }]);
    expect(accountRoutingRowsToRules(rows)).toEqual([]);
  });

  it("sends null gates for priority-only rules even when the row contains gate values", () => {
    const rows = accountRoutingRulesToRows([account], []);
    rows[0].routingPolicy = "preserve";
    rows[0].usageCeilingPrimaryPct = "invalid";
    expect(accountRoutingRowsToRules(rows)).toEqual([{
      accountId: account.accountId,
      routingPolicy: "preserve",
      overrideGates: false,
      ...nullGates,
    }]);
  });

  it("converts custom inputs to numbers and empty inputs to null", () => {
    const rows = accountRoutingRulesToRows([account], []);
    Object.assign(rows[0], {
      overrideGates: true,
      usageCeilingPrimaryPct: "80.5",
      usageCeilingSecondaryPct: " ",
      paceMarginSecondaryPct: "100",
      preResetWindowMinutes: "0",
    });
    expect(accountRoutingRowsToRules(rows)).toEqual([{
      accountId: account.accountId,
      routingPolicy: null,
      overrideGates: true,
      usageCeilingPrimaryPct: 80.5,
      usageCeilingSecondaryPct: null,
      paceMarginPrimaryPct: 0,
      paceMarginSecondaryPct: 100,
      preResetWindowMinutes: 0,
    }]);
  });

  it("preserves an all-off custom rule", () => {
    const rule: ApiKeyAccountRoutingRule = {
      accountId: account.accountId, routingPolicy: null, overrideGates: true, ...nullGates,
    };
    const rows = accountRoutingRulesToRows([account], [rule]);
    expect(rows[0].usageCeilingPrimaryPct).toBe("");
    expect(accountRoutingRowsToRules(rows)).toEqual([rule]);
  });

  it("round trips both kinds of rules, drops hidden accounts, and follows account order", () => {
    const second = createAccountSummary({ accountId: "second" });
    const custom: ApiKeyAccountRoutingRule = {
      ...nullGates,
      accountId: account.accountId,
      routingPolicy: "normal",
      overrideGates: true,
      usageCeilingSecondaryPct: 100,
      paceMarginPrimaryPct: 0,
      preResetWindowMinutes: 30,
    };
    const priority: ApiKeyAccountRoutingRule = {
      ...nullGates, accountId: second.accountId, routingPolicy: "burn_first", overrideGates: false,
    };
    const hidden: ApiKeyAccountRoutingRule = { ...priority, accountId: "hidden" };
    expect(accountRoutingRowsToRules(accountRoutingRulesToRows([account, second], [priority, hidden, custom])))
      .toEqual([custom, priority]);
  });

  it("rejects invalid custom input instead of sending an invalid number", () => {
    const rows = accountRoutingRulesToRows([account], []);
    rows[0].overrideGates = true;
    rows[0].usageCeilingPrimaryPct = "0";
    expect(() => accountRoutingRowsToRules(rows)).toThrow("Enter a number greater than 0 and at most 100.");
  });
});

describe("routing gate validation", () => {
  it.each(ROUTING_GATE_FIELDS)("accepts empty $name as off", ({ name }) => {
    expect(validateRoutingGate(name, "")).toBeUndefined();
    expect(validateRoutingGate(name, "  ")).toBeUndefined();
  });

  for (const field of ["usageCeilingPrimaryPct", "usageCeilingSecondaryPct"] as const) {
    it.each(["0", "-1", "100.1", "no", "Infinity"])(`rejects ${field} %s`, (value) => {
      expect(validateRoutingGate(field, value)).toBe("Enter a number greater than 0 and at most 100.");
    });
    it.each(["0.1", "99.9", "100"])(`accepts ${field} %s`, (value) => {
      expect(validateRoutingGate(field, value)).toBeUndefined();
    });
  }

  for (const field of ["paceMarginPrimaryPct", "paceMarginSecondaryPct"] as const) {
    it.each(["-0.1", "100.1", "no", "Infinity"])(`rejects ${field} %s`, (value) => {
      expect(validateRoutingGate(field, value)).toBe("Enter a number from 0 to 100.");
    });
    it.each(["0", "50.5", "100"])(`accepts ${field} %s`, (value) => {
      expect(validateRoutingGate(field, value)).toBeUndefined();
    });
  }

  it.each(["-1", "0.5", "no", "Infinity"])("rejects pre-reset window %s", (value) => {
    expect(validateRoutingGate("preResetWindowMinutes", value)).toBe("Enter a whole number of 0 or more.");
  });
  it.each(["0", "120", "10000"])("accepts pre-reset window %s", (value) => {
    expect(validateRoutingGate("preResetWindowMinutes", value)).toBeUndefined();
  });
});

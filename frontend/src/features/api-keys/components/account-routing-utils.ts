import { z } from "zod";

import type { AccountSummary } from "@/features/accounts/schemas";
import type { ApiKeyAccountRoutingRule } from "@/features/api-keys/schemas";

export const ROUTING_GATE_FIELDS = [
  { name: "usageCeilingPrimaryPct", label: "5h ceiling %" },
  { name: "usageCeilingSecondaryPct", label: "Weekly ceiling %" },
  { name: "paceMarginPrimaryPct", label: "5h pace margin %" },
  { name: "paceMarginSecondaryPct", label: "Weekly pace margin %" },
  { name: "preResetWindowMinutes", label: "Pre-reset window min" },
] as const;

export type RoutingGateField = (typeof ROUTING_GATE_FIELDS)[number]["name"];
export type RoutingGateInputs = Record<RoutingGateField, string>;
export type AccountRoutingRow = RoutingGateInputs & {
  accountId: string;
  routingPolicy: "inherit" | NonNullable<ApiKeyAccountRoutingRule["routingPolicy"]>;
  overrideGates: boolean;
};

const ceilingSchema = z.number().gt(0).max(100);
const marginSchema = z.number().min(0).max(100);
const windowSchema = z.number().int().min(0);

export function validateRoutingGate(field: RoutingGateField, input: string): string | undefined {
  if (input.trim() === "") return undefined;
  const value = Number(input);
  if (field === "preResetWindowMinutes") {
    return windowSchema.safeParse(value).success ? undefined : "Enter a whole number of 0 or more.";
  }
  if (field === "usageCeilingPrimaryPct" || field === "usageCeilingSecondaryPct") {
    return ceilingSchema.safeParse(value).success ? undefined : "Enter a number greater than 0 and at most 100.";
  }
  return marginSchema.safeParse(value).success ? undefined : "Enter a number from 0 to 100.";
}

export function routingGateInputs(
  values: Pick<AccountSummary, RoutingGateField>,
): RoutingGateInputs {
  return {
    usageCeilingPrimaryPct: values.usageCeilingPrimaryPct?.toString() ?? "",
    usageCeilingSecondaryPct: values.usageCeilingSecondaryPct?.toString() ?? "",
    paceMarginPrimaryPct: values.paceMarginPrimaryPct?.toString() ?? "",
    paceMarginSecondaryPct: values.paceMarginSecondaryPct?.toString() ?? "",
    preResetWindowMinutes: values.preResetWindowMinutes?.toString() ?? "",
  };
}

export function accountRoutingRulesToRows(
  accounts: AccountSummary[],
  rules: ApiKeyAccountRoutingRule[],
): AccountRoutingRow[] {
  const rulesByAccount = new Map(rules.map((rule) => [rule.accountId, rule]));
  return accounts.map((account) => {
    const rule = rulesByAccount.get(account.accountId);
    return {
      accountId: account.accountId,
      routingPolicy: rule?.routingPolicy ?? "inherit",
      overrideGates: rule?.overrideGates ?? false,
      ...routingGateInputs(rule?.overrideGates ? rule : account),
    };
  });
}

export function accountRoutingRowsToRules(rows: AccountRoutingRow[]): ApiKeyAccountRoutingRule[] {
  return rows
    .filter((row) => row.routingPolicy !== "inherit" || row.overrideGates)
    .map((row) => {
      const gateValue = (field: RoutingGateField): number | null => {
        if (!row.overrideGates || row[field].trim() === "") return null;
        const error = validateRoutingGate(field, row[field]);
        if (error) throw new Error(error);
        return Number(row[field]);
      };
      return {
        accountId: row.accountId,
        routingPolicy: row.routingPolicy === "inherit" ? null : row.routingPolicy,
        overrideGates: row.overrideGates,
        usageCeilingPrimaryPct: gateValue("usageCeilingPrimaryPct"),
        usageCeilingSecondaryPct: gateValue("usageCeilingSecondaryPct"),
        paceMarginPrimaryPct: gateValue("paceMarginPrimaryPct"),
        paceMarginSecondaryPct: gateValue("paceMarginSecondaryPct"),
        preResetWindowMinutes: gateValue("preResetWindowMinutes"),
      };
    });
}

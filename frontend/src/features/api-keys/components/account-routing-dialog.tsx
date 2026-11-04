import { useState } from "react";

import { AlertMessage } from "@/components/alert-message";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { useAccounts } from "@/features/accounts/hooks/use-accounts";
import type { AccountSummary } from "@/features/accounts/schemas";
import type { ApiKey, ApiKeyAccountRoutingRulesUpdateRequest } from "@/features/api-keys/schemas";
import { ACCOUNT_ROUTING_POLICIES } from "@/features/api-keys/schemas";
import { PROVIDER_OPENAI } from "@/utils/constants";
import { getErrorMessageOrNull } from "@/utils/errors";
import { formatProviderLabel } from "@/utils/formatters";

import {
  accountRoutingRowsToRules,
  accountRoutingRulesToRows,
  ROUTING_GATE_FIELDS,
  routingGateInputs,
  validateRoutingGate,
  type AccountRoutingRow,
} from "./account-routing-utils";

const POLICY_LABELS = { burn_first: "Use first", normal: "Normal", preserve: "Use last" } as const;

export type AccountRoutingDialogProps = {
  open: boolean;
  busy: boolean;
  apiKey: ApiKey | null;
  onOpenChange: (open: boolean) => void;
  onSubmit: (payload: ApiKeyAccountRoutingRulesUpdateRequest) => Promise<void>;
};

type AccountRoutingFormProps = {
  apiKey: ApiKey;
  accounts: AccountSummary[];
  accountsUnavailable: boolean;
  busy: boolean;
  onSubmit: AccountRoutingDialogProps["onSubmit"];
  onClose: () => void;
};

function AccountRoutingForm({ apiKey, accounts, accountsUnavailable, busy, onSubmit, onClose }: AccountRoutingFormProps) {
  // Keep the accounts stable while editing, even if the shared query polls again.
  const [visibleAccounts] = useState(() => accounts.filter((account) =>
    !apiKey.accountAssignmentScopeEnabled || apiKey.assignedAccountIds.includes(account.accountId),
  ));
  const [rows, setRows] = useState(() => accountRoutingRulesToRows(visibleAccounts, apiKey.accountRoutingRules));
  const invalid = rows.some((row) => row.overrideGates &&
    ROUTING_GATE_FIELDS.some(({ name }) => validateRoutingGate(name, row[name])),
  );

  const updateRow = (accountId: string, patch: Partial<AccountRoutingRow>) => {
    setRows((current) => current.map((row) => row.accountId === accountId ? { ...row, ...patch } : row));
  };

  const handleSubmit = async () => {
    if (busy || invalid || accountsUnavailable) return;
    try {
      await onSubmit({ rules: accountRoutingRowsToRules(rows) });
    } catch {
      // The mutation shows the error toast; keep the draft available for retry.
      return;
    }
    onClose();
  };

  return (
    <form onSubmit={(event) => { event.preventDefault(); void handleSubmit(); }} noValidate className="space-y-4">
      <div className="max-h-[60vh] space-y-3 overflow-y-auto overscroll-contain pr-1">
        <p className="text-xs text-muted-foreground">
          {apiKey.accountAssignmentScopeEnabled ? "Showing this key’s assigned accounts." : "Showing all accounts."}
        </p>
        {rows.length === 0 ? <p className="text-sm text-muted-foreground">No accounts available.</p> : null}
        {rows.map((row, index) => {
          const account = visibleAccounts[index];
          const label = account.alias || account.displayName || account.email;
          const provider = account.provider ?? PROVIDER_OPENAI;
          const inheritedPolicy = POLICY_LABELS[account.routingPolicy ?? "normal"];
          return (
            <fieldset key={row.accountId} disabled={busy} aria-label={label} className="space-y-3 rounded-lg border bg-muted/30 p-3">
              <legend className="sr-only">{label}</legend>
              <div className="flex items-center gap-2">
                <span className="min-w-0 truncate text-sm font-medium" title={label}>{label}</span>
                <span className="rounded border px-1.5 py-0.5 text-xs text-muted-foreground">
                  {provider === PROVIDER_OPENAI ? "ChatGPT" : formatProviderLabel(provider)}
                </span>
              </div>
              <div className="grid gap-3 sm:grid-cols-2">
                <div className="space-y-1">
                  <label htmlFor={`priority-${row.accountId}`} className="text-xs text-muted-foreground">Priority</label>
                  <Select value={row.routingPolicy} disabled={busy} onValueChange={(value) => {
                    if (value === "inherit" || ACCOUNT_ROUTING_POLICIES.some((policy) => policy === value)) {
                      updateRow(row.accountId, { routingPolicy: value as AccountRoutingRow["routingPolicy"] });
                    }
                  }}>
                    <SelectTrigger id={`priority-${row.accountId}`} aria-label={`Priority for ${label}`} className="w-full"><SelectValue /></SelectTrigger>
                    <SelectContent>
                      <SelectItem value="inherit"><span className="text-muted-foreground">Inherit ({inheritedPolicy})</span></SelectItem>
                      {ACCOUNT_ROUTING_POLICIES.map((policy) => <SelectItem key={policy} value={policy}>{POLICY_LABELS[policy]}</SelectItem>)}
                    </SelectContent>
                  </Select>
                </div>
                <div className="space-y-1">
                  <label htmlFor={`limits-${row.accountId}`} className="text-xs text-muted-foreground">Limits</label>
                  <Select value={row.overrideGates ? "custom" : "inherit"} disabled={busy} onValueChange={(value) => {
                    // Custom starts as an editable copy of the account's current limits.
                    updateRow(row.accountId, value === "custom"
                      ? { overrideGates: true, ...routingGateInputs(account) }
                      : { overrideGates: false });
                  }}>
                    <SelectTrigger id={`limits-${row.accountId}`} aria-label={`Limits for ${label}`} className="w-full"><SelectValue /></SelectTrigger>
                    <SelectContent>
                      <SelectItem value="inherit">Inherit account limits</SelectItem>
                      <SelectItem value="custom">Custom for this key</SelectItem>
                    </SelectContent>
                  </Select>
                </div>
              </div>
              {row.overrideGates ? (
                <div className="space-y-2">
                  <p id={`gate-hint-${row.accountId}`} className="text-xs text-muted-foreground">Empty switches the gate off for this key.</p>
                  <div className="grid gap-3 sm:grid-cols-2">
                    {ROUTING_GATE_FIELDS.map(({ name, label: fieldLabel }) => {
                      const id = `${row.accountId}-${name}`;
                      const error = validateRoutingGate(name, row[name]);
                      return (
                        <div key={name} className="space-y-1">
                          <label htmlFor={id} className="text-xs text-muted-foreground">{fieldLabel}</label>
                          <Input id={id} type="number" step={name === "preResetWindowMinutes" ? 1 : "any"}
                            value={row[name]} placeholder={account[name]?.toString() ?? "off"}
                            aria-invalid={!!error} aria-describedby={`${id}-error gate-hint-${row.accountId}`}
                            onChange={(event) => updateRow(row.accountId, { [name]: event.target.value })} />
                          {error ? <p id={`${id}-error`} className="text-destructive text-xs">{error}</p> : null}
                        </div>
                      );
                    })}
                  </div>
                </div>
              ) : null}
            </fieldset>
          );
        })}
      </div>
      <DialogFooter>
        <Button type="button" variant="outline" onClick={onClose} disabled={busy}>Cancel</Button>
        <Button type="submit" disabled={busy || invalid || accountsUnavailable}>{busy ? "Saving..." : "Save"}</Button>
      </DialogFooter>
    </form>
  );
}

function AccountRoutingAccounts(props: Omit<AccountRoutingFormProps, "accounts" | "accountsUnavailable">) {
  const { accountsQuery } = useAccounts();
  return (
    <>
      {accountsQuery.error ? (
        <AlertMessage variant="error">
          {getErrorMessageOrNull(accountsQuery.error) || "Failed to load accounts"}
          <Button type="button" size="sm" variant="outline" disabled={accountsQuery.isFetching}
            onClick={() => { void accountsQuery.refetch(); }}>Retry</Button>
        </AlertMessage>
      ) : null}
      {accountsQuery.data ? (
        <AccountRoutingForm {...props} accounts={accountsQuery.data} accountsUnavailable={!!accountsQuery.error} />
      ) : accountsQuery.isPending ? <p className="text-sm text-muted-foreground">Loading accounts...</p> : null}
    </>
  );
}

export function AccountRoutingDialog({ open, busy, apiKey, onOpenChange, onSubmit }: AccountRoutingDialogProps) {
  return (
    <Dialog open={open} onOpenChange={(next) => { if (!busy) onOpenChange(next); }}>
      <DialogContent className="sm:max-w-2xl">
        <DialogHeader>
          <DialogTitle>Account routing</DialogTitle>
          <DialogDescription>Choose how this key ranks each account and, if needed, give it its own limits. Which accounts the key can reach is set under Edit.</DialogDescription>
        </DialogHeader>
        {open && apiKey ? (
          <AccountRoutingAccounts key={apiKey.id} apiKey={apiKey} busy={busy} onSubmit={onSubmit} onClose={() => onOpenChange(false)} />
        ) : null}
      </DialogContent>
    </Dialog>
  );
}

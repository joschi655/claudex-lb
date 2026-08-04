import { Clock } from "lucide-react";

import type { AccountSummary } from "@/features/dashboard/schemas";
import { cn } from "@/lib/utils";
import { formatResetRelative, formatWindowLabel } from "@/utils/formatters";

function formatQuotaLabel(value: string): string {
  return value.replace(/_/g, " ").replace(/\b\w/g, (character) => character.toUpperCase());
}

function resetLabel(resetAt: number | null | undefined): string | null {
  if (resetAt == null) {
    return null;
  }
  const remainingMs = resetAt * 1000 - Date.now();
  return remainingMs <= 0 ? "Resetting" : `Resets ${formatResetRelative(remainingMs)}`;
}

function QuotaWindow({
  window,
  windowName,
}: {
  window: { usedPercent: number; resetAt?: number | null; windowMinutes?: number | null };
  windowName: "primary" | "secondary";
}) {
  const usedPercent = Math.max(0, Math.min(100, window.usedPercent));
  const reset = resetLabel(window.resetAt);

  return (
    <div className="space-y-1.5">
      <div className="flex items-center justify-between gap-3 text-xs">
        <span className="text-muted-foreground">
          {formatWindowLabel(windowName, window.windowMinutes ?? null)}
        </span>
        <span className="shrink-0 tabular-nums font-medium">{Math.round(usedPercent)}% used</span>
      </div>
      <div className="h-1.5 overflow-hidden rounded-full bg-muted">
        <div
          className={cn(
            "h-full rounded-full",
            usedPercent > 95
              ? "bg-red-500"
              : usedPercent > 80
                ? "bg-amber-500"
                : "bg-emerald-500",
          )}
          style={{ width: `${usedPercent}%` }}
        />
      </div>
      {reset ? (
        <p className="flex items-center gap-1 text-[11px] text-muted-foreground">
          <Clock className="h-3 w-3" aria-hidden="true" />
          {reset}
        </p>
      ) : null}
    </div>
  );
}

export function AnthropicCapacityPanel({ accounts }: { accounts: AccountSummary[] }) {
  const anthropicAccounts = accounts.filter((account) => account.provider === "anthropic");

  return (
    <section className="space-y-4">
      <div className="flex items-center gap-3">
        <h2 className="text-[13px] font-medium uppercase tracking-wider text-muted-foreground">
          Claude throughput limits
        </h2>
        <div className="h-px flex-1 bg-border" />
      </div>
      {anthropicAccounts.length === 0 ? (
        <p className="text-sm text-muted-foreground">No Claude accounts in this scope.</p>
      ) : (
        <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-3">
          {anthropicAccounts.map((account) => (
            <div key={account.accountId} className="min-w-0 rounded-md border bg-card p-3">
              <div className="mb-3 min-w-0">
                <p className="truncate text-sm font-medium">
                  {account.alias || account.displayName || account.email}
                </p>
                <p className="text-xs text-muted-foreground">Per-key Anthropic limits</p>
              </div>
              {account.additionalQuotas.length === 0 ? (
                <p className="text-xs text-muted-foreground">
                  No rate-limit snapshot yet. Limits appear after a relayed request.
                </p>
              ) : (
                <div className="space-y-3">
                  {account.additionalQuotas.map((quota) => (
                    <div key={quota.quotaKey ?? quota.limitName} className="space-y-2 border-t pt-3 first:border-t-0 first:pt-0">
                      <p className="text-xs font-medium">
                        {quota.displayLabel ?? formatQuotaLabel(quota.limitName)}
                      </p>
                      {quota.primaryWindow ? (
                        <QuotaWindow window={quota.primaryWindow} windowName="primary" />
                      ) : null}
                      {quota.secondaryWindow ? (
                        <QuotaWindow window={quota.secondaryWindow} windowName="secondary" />
                      ) : null}
                    </div>
                  ))}
                </div>
              )}
            </div>
          ))}
        </div>
      )}
    </section>
  );
}

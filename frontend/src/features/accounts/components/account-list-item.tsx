import { Flame, Pin, Shield, ShieldCheck } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { cn } from "@/lib/utils";
import { isEmailLabel } from "@/components/blur-email";
import { usePrivacyStore } from "@/hooks/use-privacy";
import { useAccountQuotaDisplayStore } from "@/hooks/use-account-quota-display";
import { StatusBadge } from "@/components/status-badge";
import { MiniQuotaBar } from "@/components/mini-quota-bar";
import { ProviderBadge } from "@/components/provider-badge";
import type { NextUpMark } from "@/features/accounts/next-up";
import type { LiveQuotaPool } from "@/features/accounts/quota-kind";
import {
  describeQuotaPool,
  formatQuotaPoolAmounts,
  resolveLiveQuotaPool,
  resolveQuotaKind,
} from "@/features/accounts/quota-kind";
import type {
  AccountRoutingPolicy,
  AccountSummary,
} from "@/features/accounts/schemas";
import { normalizeStatus } from "@/utils/account-status";
import { formatCompactAccountId } from "@/utils/account-identifiers";
import {
  formatDateTimeInline,
  formatPercentNullable,
  formatQuotaResetLabel,
  formatSlug,
} from "@/utils/formatters";

export type AccountListItemProps = {
  account: AccountSummary;
  selected: boolean;
  showAccountId?: boolean;
  /** Set when this account is the one the pool would route the next request to. */
  nextUp?: NextUpMark | null;
  onSelect: (accountId: string) => void;
};

export function AccountListItem({
  account,
  selected,
  showAccountId = false,
  nextUp = null,
  onSelect,
}: AccountListItemProps) {
  const blurred = usePrivacyStore((s) => s.blurred);
  const quotaDisplay = useAccountQuotaDisplayStore((s) => s.quotaDisplay);
  const status = normalizeStatus(account.status);
  const title = account.displayName || account.email;
  const titleIsEmail = isEmailLabel(title, account.email);
  const emailSubtitle = account.displayName && account.displayName !== account.email
    ? account.email
    : null;
  const workspaceLabel = account.chatgptAccountId || account.workspaceLabel || account.workspaceId || "Personal / unknown workspace";
  const seatLabel = account.seatType ? ` | ${formatSlug(account.seatType)}` : "";
  const slotSubtitle = `${formatSlug(account.planType)} | ${workspaceLabel}${seatLabel}`;
  const idSuffix = showAccountId ? ` | ID ${formatCompactAccountId(account.accountId)}` : "";
  const primary = account.usage?.primaryRemainingPercent ?? null;
  const secondary = account.usage?.secondaryRemainingPercent ?? null;
  const monthly = account.usage?.monthlyRemainingPercent ?? null;
  const hasPrimaryWindow =
    account.windowMinutesPrimary != null ||
    primary !== null ||
    account.resetAtPrimary != null;
  const hasSecondaryWindow =
    account.windowMinutesSecondary != null ||
    secondary !== null ||
    account.resetAtSecondary != null;
  const hasMonthlyWindow =
    account.windowMinutesMonthly != null ||
    monthly !== null ||
    account.resetAtMonthly != null;
  // A usage-based seat bills against a dollar budget and may report no rolling
  // window at all. Every window branch below keys off a window it will never
  // have, so without the budget row it renders no quota information whatsoever
  // -- the one thing its requirement says must not happen.
  const usageBased = resolveQuotaKind(account) === "usage_based";
  // The pool the seat can still spend from, which is not always the plan
  // budget: once that is gone the extra-usage pool behind it is what keeps the
  // seat serving, and showing the spent budget instead reports a seat as dead
  // while it is still a candidate for the next request.
  const livePool = resolveLiveQuotaPool(account);
  const showBudgetRow = usageBased;
  const monthlyOnly = !usageBased && hasMonthlyWindow && !hasPrimaryWindow && !hasSecondaryWindow;
  const showMonthlyRow = monthlyOnly;
  const showPrimaryRow =
    !usageBased && !monthlyOnly && hasPrimaryWindow && (quotaDisplay !== "weekly" || !hasSecondaryWindow);
  const showSecondaryRow =
    !usageBased && !monthlyOnly && hasSecondaryWindow && (quotaDisplay !== "5h" || !hasPrimaryWindow);
  const visibleQuotaRows =
    Number(showPrimaryRow) + Number(showSecondaryRow) + Number(showMonthlyRow) + Number(showBudgetRow);
  const showRoutingPolicy = status !== "reauth" && status !== "deactivated";
  const warmupLabel = account.limitWarmupEnabled ? "Warm-up on" : "Warm-up off";
  const warmupMeta = account.limitWarmup
    ? `${formatSlug(account.limitWarmup.status)} | ${formatSlug(account.limitWarmup.model)} | ${formatDateTimeInline(account.limitWarmup.completedAt ?? account.limitWarmup.attemptedAt)}`
    : "No attempts";
  const availableResetCredits = account.availableResetCredits ?? 0;
  const resetBadgeLabel = availableResetCredits > 99 ? "99+" : String(availableResetCredits);

  return (
    <button
      type="button"
      onClick={() => onSelect(account.accountId)}
      className={cn(
        "relative min-w-0 w-full rounded-lg px-3 py-2.5 text-left transition-colors",
        selected ? "bg-primary/8 ring-1 ring-primary/25" : "hover:bg-muted/50",
      )}
    >
      {availableResetCredits > 0 ? (
        <span className="absolute -top-1 -right-1 grid h-5 min-w-[1.25rem] place-items-center rounded-full bg-primary px-1 text-[10px] font-medium text-primary-foreground">
          {resetBadgeLabel}
        </span>
      ) : null}
      <div className="flex items-start gap-2.5">
        <div className="min-w-0 flex-1">
          <p className="flex items-center gap-1.5 truncate text-sm font-medium">
            <ProviderBadge provider={account.provider} />
            {titleIsEmail && blurred ? (
              <span className="privacy-blur">{title}</span>
            ) : (
              title
            )}
          </p>
          <p className="truncate text-xs text-muted-foreground" title={showAccountId ? `Account ID ${account.accountId}` : undefined}>
            {emailSubtitle ? <><span className={blurred ? "privacy-blur" : undefined}>{emailSubtitle}</span> | {slotSubtitle}{idSuffix}</> : <>{slotSubtitle}{idSuffix}</>}
          </p>
        </div>
        {showRoutingPolicy && account.pinned === true ? <PinnedBadge /> : null}
        {showRoutingPolicy ? (
          <RoutingPolicyBadge
            policy={account.routingPolicy as AccountRoutingPolicy | undefined}
          />
        ) : null}
        {account.securityWorkAuthorized === true ? (
          <ShieldCheck
            className="h-3.5 w-3.5 text-emerald-600"
            aria-label="Trusted Access for Cyber"
          />
        ) : null}
        {nextUp ? <NextUpBadge certain={nextUp.certain} /> : <StatusBadge status={status} />}
      </div>
      <div
        className={cn(
          "mt-2 grid gap-2",
          visibleQuotaRows > 1 ? "grid-cols-1 sm:grid-cols-2" : "grid-cols-1",
        )}
      >
        {showMonthlyRow ? (
          <MiniQuotaRow
            label="Monthly"
            percent={monthly}
            resetAt={account.resetAtMonthly}
          />
        ) : null}
        {showPrimaryRow ? (
          <MiniQuotaRow
            label="5h"
            percent={primary}
            resetAt={account.resetAtPrimary}
          />
        ) : null}
        {showSecondaryRow ? (
          <MiniQuotaRow
            label="Weekly"
            percent={secondary}
            resetAt={account.resetAtSecondary}
          />
        ) : null}
        {showBudgetRow ? <MiniBudgetRow pool={livePool} /> : null}
      </div>
      <div className="mt-2 flex min-w-0 items-center justify-between gap-2 text-[10px] text-muted-foreground">
        <span className="shrink-0">{warmupLabel}</span>
        <span className="min-w-0 truncate">{warmupMeta}</span>
      </div>
    </button>
  );
}

// Replaces the status badge rather than sitting beside it: being next already
// implies the account is able to serve, and a second badge on the one row that
// matters costs the width the account name needs.
//
// "Next" rather than "Serving": the pool reports where a new request would go,
// which is answerable on an idle pool and stays right through a pin, a pause,
// or a limit — all the moments a last-request badge went stale.
function NextUpBadge({ certain }: { certain: boolean }) {
  return (
    <Badge
      variant="outline"
      className="shrink-0 gap-1.5 border-blue-500/20 bg-blue-500/15 px-1.5 text-[11px] text-blue-700 dark:text-blue-400"
      title={
        certain
          ? "The next request lands here"
          : "Most likely next: the routing strategy draws at random among the accounts with capacity"
      }
    >
      <span className="relative flex h-1.5 w-1.5" aria-hidden>
        <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-current opacity-75" />
        <span className="relative inline-flex h-1.5 w-1.5 rounded-full bg-current" />
      </span>
      {certain ? "Next" : "Likely next"}
    </Badge>
  );
}

// Sits beside the routing policy, not in place of it: the pin says this account
// is the only candidate, the policy says how it ranks once the pin is gone.
function PinnedBadge() {
  return (
    <Badge
      variant="outline"
      className="shrink-0 gap-1 border-emerald-300 bg-emerald-50 px-1.5 text-[11px] text-emerald-700 dark:border-emerald-500/30 dark:bg-emerald-500/10 dark:text-emerald-300"
    >
      <Pin className="h-3 w-3" aria-hidden="true" />
      Pinned
    </Badge>
  );
}

function RoutingPolicyBadge({
  policy,
}: {
  policy: AccountRoutingPolicy | undefined;
}) {
  if (policy === "burn_first") {
    return (
      <Badge
        variant="outline"
        className="shrink-0 gap-1 border-amber-300 bg-amber-50 px-1.5 text-[11px] text-amber-700 dark:border-amber-500/30 dark:bg-amber-500/10 dark:text-amber-300"
      >
        <Flame className="h-3 w-3" aria-hidden="true" />
        Burn first
      </Badge>
    );
  }
  if (policy === "preserve") {
    return (
      <Badge
        variant="outline"
        className="shrink-0 gap-1 border-sky-300 bg-sky-50 px-1.5 text-[11px] text-sky-700 dark:border-sky-500/30 dark:bg-sky-500/10 dark:text-sky-300"
      >
        <Shield className="h-3 w-3" aria-hidden="true" />
        Preserve
      </Badge>
    );
  }
  return (
    <Badge
      variant="outline"
      className="shrink-0 px-1.5 text-[11px] text-muted-foreground"
    >
      Normal
    </Badge>
  );
}

function MiniQuotaRow({
  label,
  percent,
  resetAt,
}: {
  label: string;
  percent: number | null;
  resetAt: string | null | undefined;
}) {
  return (
    <div className="space-y-1">
      <div className="flex items-center justify-between text-[11px]">
        <span className="text-muted-foreground">{label}</span>
        <span className="tabular-nums font-medium">
          {formatPercentNullable(percent)}
        </span>
      </div>
      <MiniQuotaBar
        aria-label={`${label} credits remaining`}
        percent={percent}
        testId={`mini-quota-track-${label.toLowerCase()}`}
      />
      <div className="text-[10px] text-muted-foreground">
        {formatMiniQuotaResetLabel(resetAt ?? null)}
      </div>
    </div>
  );
}

// The dollar pool's counterpart to MiniQuotaRow. The bar reads left-to-spend so
// it fills and empties the same way a window bar does; showing "used" here would
// make a nearly-spent pool look like a nearly-full window.
function MiniBudgetRow({ pool }: { pool: LiveQuotaPool | null }) {
  // Rendered even with nothing to show. An account declared usage-based whose
  // budget has not been read yet says so, rather than reverting to the window
  // bars the operator set the field to get rid of.
  const remainingPercent = pool?.remainingPercent ?? null;

  return (
    <div className="space-y-1">
      <div className="flex items-center justify-between text-[11px]">
        {/* Named, so a plan budget is never read as the top-up behind it. */}
        <span className="text-muted-foreground">{pool?.label ?? "Budget"}</span>
        <span className="tabular-nums font-medium">
          {formatPercentNullable(remainingPercent)}
        </span>
      </div>
      <MiniQuotaBar
        aria-label={`${pool?.label ?? "Budget"} remaining`}
        percent={remainingPercent}
        testId="mini-quota-track-budget"
      />
      <div className="text-[10px] text-muted-foreground">
        {pool?.resetAt && !formatQuotaPoolAmounts(pool)
          ? formatMiniQuotaResetLabel(pool.resetAt)
          : describeQuotaPool(pool)}
      </div>
    </div>
  );
}

function formatMiniQuotaResetLabel(resetAt: string | null): string {
  const label = formatQuotaResetLabel(resetAt);
  return label.startsWith("Reset ") ? label : `Reset ${label}`;
}

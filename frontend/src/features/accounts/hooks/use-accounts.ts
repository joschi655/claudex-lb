import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useRef } from "react";
import { toast } from "sonner";

import {
  consumeRateLimitResetCredit,
  consumeAccountUsageResetCredit,
  deleteAccount,
  exportAccountAuth,
  getAccountTrends,
  getAccountUsageResetCredits,
  getNextAccounts,
  getRateLimitResetCredits,
  importAccount,
  listAccounts,
  pauseAccount,
  probeAccount,
  reactivateAccount,
  setAccountAlias,
  updateAccount,
  updateAccountLimitWarmup,
  updateAccountPaceGates,
  updateAccountPin,
  updateAccountQuotaKind,
  updateAccountRoutingPolicy,
} from "@/features/accounts/api";
import type {
  AccountPaceGatesUpdate,
  AccountQuotaKind,
  AccountRoutingPolicy,
  AccountUsageResetConsumeResponse,
} from "@/features/accounts/schemas";

async function invalidateAccountRelatedQueries(queryClient: ReturnType<typeof useQueryClient>, accountId?: string) {
  const invalidations = [
    queryClient.invalidateQueries({ queryKey: ["accounts", "list"] }),
    // Anything that changes an account changes who serves next: pausing,
    // pinning, and re-authenticating all move the answer immediately, well
    // before the next poll would notice.
    queryClient.invalidateQueries({ queryKey: ["accounts", "next-up"] }),
    queryClient.invalidateQueries({ queryKey: ["dashboard", "overview"] }),
    queryClient.invalidateQueries({ queryKey: ["dashboard", "projections"] }),
  ];
  if (accountId) {
    invalidations.push(queryClient.invalidateQueries({ queryKey: ["accounts", "trends", accountId] }));
    invalidations.push(queryClient.invalidateQueries({ queryKey: ["accounts", "usage-reset-credits", accountId] }));
  } else {
    invalidations.push(queryClient.invalidateQueries({ queryKey: ["accounts", "trends"] }));
    invalidations.push(queryClient.invalidateQueries({ queryKey: ["accounts", "usage-reset-credits"] }));
  }
  await Promise.all(invalidations);
}

function usageResetToastMessage(data: AccountUsageResetConsumeResponse): string {
  const changed =
    data.primaryUsedPercentBefore !== data.primaryUsedPercentAfter ||
    data.secondaryUsedPercentBefore !== data.secondaryUsedPercentAfter ||
    data.accountStatusBefore !== data.accountStatusAfter;
  if (data.code === "reset") {
    return changed ? "Usage reset applied" : "Usage reset applied; upstream values are unchanged";
  }
  if (data.code === "already_redeemed") {
    return "Usage reset was already applied";
  }
  if (data.code === "no_credit") {
    return "No usage reset credits available";
  }
  if (data.code === "nothing_to_reset") {
    return "Nothing to reset";
  }
  return "Usage reset request completed";
}

function createRedeemRequestId(): string {
  return globalThis.crypto?.randomUUID?.() ?? `dashboard-${Date.now()}-${Math.random().toString(36).slice(2)}`;
}

/**
 * Account mutation actions without the polling query.
 * Use this when you need account actions but already have account data
 * from another source (e.g. the dashboard overview query).
 */
export function useAccountMutations() {
  const queryClient = useQueryClient();
  const usageResetRedeemRequestRef = useRef<{
    accountId: string;
    redeemRequestId: string;
  } | null>(null);

  const importMutation = useMutation({
    mutationFn: importAccount,
    onSuccess: () => {
      toast.success("Account imported");
      void invalidateAccountRelatedQueries(queryClient);
    },
    onError: (error: Error) => {
      toast.error(error.message || "Import failed");
    },
  });

  const pauseMutation = useMutation({
    mutationFn: pauseAccount,
    onSuccess: () => {
      toast.success("Account paused");
      void invalidateAccountRelatedQueries(queryClient);
    },
    onError: (error: Error) => {
      toast.error(error.message || "Pause failed");
    },
  });

  const resumeMutation = useMutation({
    mutationFn: reactivateAccount,
    onSuccess: () => {
      toast.success("Account resumed");
      void invalidateAccountRelatedQueries(queryClient);
    },
    onError: (error: Error) => {
      toast.error(error.message || "Resume failed");
    },
  });

  const setAliasMutation = useMutation({
    mutationFn: ({ accountId, alias }: { accountId: string; alias: string | null }) =>
      setAccountAlias(accountId, alias),
    onSuccess: () => {
      toast.success("Account alias updated");
      void invalidateAccountRelatedQueries(queryClient);
    },
    onError: (error: Error) => {
      toast.error(error.message || "Alias update failed");
    },
  });

  const deleteMutation = useMutation({
    mutationFn: ({ accountId, deleteHistory }: { accountId: string; deleteHistory: boolean }) =>
      deleteAccount(accountId, deleteHistory),
    onSuccess: () => {
      toast.success("Account deleted");
      void invalidateAccountRelatedQueries(queryClient);
    },
    onError: (error: Error) => {
      toast.error(error.message || "Delete failed");
    },
  });

  const probeMutation = useMutation({
    mutationFn: ({ accountId, model }: { accountId: string; model?: string }) =>
      probeAccount(accountId, model ? { model } : undefined),
    onSuccess: (_data, variables) => {
      toast.success("Account probed");
      void invalidateAccountRelatedQueries(queryClient, variables.accountId);
    },
    onError: (error: Error) => {
      toast.error(error.message || "Probe failed");
    },
  });

  const usageResetMutation = useMutation({
    mutationFn: ({ accountId }: { accountId: string }) => {
      if (usageResetRedeemRequestRef.current?.accountId !== accountId) {
        usageResetRedeemRequestRef.current = {
          accountId,
          redeemRequestId: createRedeemRequestId(),
        };
      }
      return consumeAccountUsageResetCredit(accountId, {
        redeemRequestId: usageResetRedeemRequestRef.current.redeemRequestId,
      });
    },
    onSuccess: async (data, variables) => {
      usageResetRedeemRequestRef.current = null;
      await invalidateAccountRelatedQueries(queryClient, variables.accountId);
      toast.success(usageResetToastMessage(data));
    },
    onError: (error: Error) => {
      toast.error(error.message || "Usage reset failed");
    },
  });

  const limitWarmupMutation = useMutation({
    mutationFn: ({ accountId, enabled }: { accountId: string; enabled: boolean }) =>
      updateAccountLimitWarmup(accountId, enabled),
    onSuccess: (data) => {
      toast.success(data.enabled ? "Limit warm-up enabled" : "Limit warm-up disabled");
      void invalidateAccountRelatedQueries(queryClient);
    },
    onError: (error: Error) => {
      toast.error(error.message || "Limit warm-up update failed");
    },
  });

  const routingPolicyMutation = useMutation({
    mutationFn: ({
      accountId,
      routingPolicy,
    }: {
      accountId: string;
      routingPolicy: AccountRoutingPolicy;
    }) => updateAccountRoutingPolicy(accountId, routingPolicy),
    onSuccess: (data) => {
      const label =
        data.routingPolicy === "normal" ? "normal" : data.routingPolicy.replace("_", "-");
      toast.success(`Account routing policy set to ${label}`);
      void invalidateAccountRelatedQueries(queryClient);
    },
    onError: (error: Error) => {
      toast.error(error.message || "Routing policy update failed");
    },
  });

  const pinMutation = useMutation({
    mutationFn: ({ accountId, pinned }: { accountId: string; pinned: boolean }) =>
      updateAccountPin(accountId, pinned),
    onSuccess: (data) => {
      // Naming the policy on unpin is the point of echoing it back: the old
      // pin flattened it, and an operator needs to see where the seat landed.
      toast.success(
        data.pinned
          ? "Account pinned"
          : `Account unpinned; routing policy ${data.routingPolicy.replace("_", " ")}`,
      );
      void invalidateAccountRelatedQueries(queryClient);
    },
    onError: (error: Error) => {
      toast.error(error.message || "Pin update failed");
    },
  });

  const quotaKindMutation = useMutation({
    mutationFn: ({ accountId, quotaKind }: { accountId: string; quotaKind: AccountQuotaKind }) =>
      updateAccountQuotaKind(accountId, quotaKind),
    onSuccess: (data) => {
      toast.success(
        data.quotaKind === "auto"
          ? "Quota display follows the account's own usage data"
          : `Quota display set to ${data.quotaKind === "usage_based" ? "usage-based" : "subscription"}`,
      );
      void invalidateAccountRelatedQueries(queryClient);
    },
    onError: (error: Error) => {
      toast.error(error.message || "Quota display update failed");
    },
  });

  const paceGatesMutation = useMutation({
    mutationFn: ({
      accountId,
      gates,
    }: {
      accountId: string;
      gates: AccountPaceGatesUpdate;
    }) => updateAccountPaceGates(accountId, gates),
    onSuccess: () => {
      toast.success("Pace gates updated");
      void invalidateAccountRelatedQueries(queryClient);
    },
    onError: (error: Error) => {
      toast.error(error.message || "Pace gate update failed");
    },
  });

  const exportAuthMutation = useMutation({
    mutationFn: exportAccountAuth,
    onSuccess: () => {
      toast.success("Account exported");
    },
    onError: (error: Error) => {
      toast.error(error.message || "Export failed");
    },
  });

  const updateMutation = useMutation({
    mutationFn: ({ accountId, securityWorkAuthorized }: { accountId: string; securityWorkAuthorized: boolean }) =>
      updateAccount(accountId, { securityWorkAuthorized }),
    onSuccess: () => {
      toast.success("Account updated");
      void invalidateAccountRelatedQueries(queryClient);
    },
    onError: (error: Error) => {
      toast.error(error.message || "Update failed");
    },
  });

  const resetCreditConsumeMutation = useMutation({
    mutationFn: ({ accountId, redeemRequestId }: { accountId: string; redeemRequestId?: string }) =>
      consumeRateLimitResetCredit(accountId, redeemRequestId ? { redeemRequestId } : undefined),
    onSuccess: (data) => {
      const resetCount = data.windowsReset ?? 0;
      toast.success(
        `Rate-limit window${resetCount === 1 ? "" : "s"} reset (${resetCount})`,
      );
      void queryClient.invalidateQueries({ queryKey: ["accounts", "list"] });
      // Redeeming a credit is the mutation that flips an account from
      // rate_limited back to active, so it is exactly the one that changes who
      // serves next.
      void queryClient.invalidateQueries({ queryKey: ["accounts", "next-up"] });
      void queryClient.invalidateQueries({ queryKey: ["accounts", "trends"] });
      void queryClient.invalidateQueries({ queryKey: ["accounts", "reset-credits"] });
      void queryClient.invalidateQueries({ queryKey: ["dashboard", "overview"] });
      void queryClient.invalidateQueries({ queryKey: ["dashboard", "projections"] });
    },
    onError: (error: Error) => {
      toast.error(error.message || "Reset credit redeem failed");
    },
  });

  return {
    importMutation,
    pauseMutation,
    resumeMutation,
    setAliasMutation,
    deleteMutation,
    probeMutation,
    usageResetMutation,
    exportAuthMutation,
    limitWarmupMutation,
    routingPolicyMutation,
    pinMutation,
    quotaKindMutation,
    paceGatesMutation,
    updateMutation,
    resetCreditConsumeMutation,
  };
}

export function useRateLimitResetCredits(
  accountId: string | null,
  enabled: boolean,
) {
  return useQuery({
    queryKey: ["accounts", "reset-credits", accountId],
    queryFn: () => getRateLimitResetCredits(accountId as string),
    enabled: enabled && !!accountId,
    staleTime: 0,
  });
}

export function useAccountTrends(accountId: string | null) {
  return useQuery({
    queryKey: ["accounts", "trends", accountId],
    queryFn: () => getAccountTrends(accountId!),
    enabled: !!accountId,
    staleTime: 5 * 60_000,
    refetchInterval: 5 * 60_000,
    refetchIntervalInBackground: false,
  });
}

export function useAccountUsageResetCredits(accountId: string | null) {
  return useQuery({
    queryKey: ["accounts", "usage-reset-credits", accountId],
    queryFn: () => getAccountUsageResetCredits(accountId!),
    enabled: !!accountId,
    staleTime: 60_000,
  });
}

/**
 * Which account each provider would route the next request to.
 *
 * Polled on the same cadence as the account list, since the two are read
 * together and a next-up answer that lags the account beside it is worse than
 * no answer at all.
 */
export function useNextAccounts() {
  return useQuery({
    queryKey: ["accounts", "next-up"],
    queryFn: getNextAccounts,
    refetchInterval: 30_000,
    refetchIntervalInBackground: false,
  });
}

export function useAccounts() {
  const { data, error, isFetching, isLoading, isPending, isSuccess, refetch } = useQuery({
    queryKey: ["accounts", "list"],
    queryFn: listAccounts,
    select: (data) => data.accounts,
    refetchInterval: 30_000,
    refetchIntervalInBackground: false,
  });
  const accountsQuery = { data, error, isFetching, isLoading, isPending, isSuccess, refetch };

  const mutations = useAccountMutations();

  return { accountsQuery, ...mutations };
}

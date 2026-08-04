import { useQuery } from "@tanstack/react-query";

import { getDashboardOverview, getDashboardProjections } from "@/features/dashboard/api";
import {
  DEFAULT_OVERVIEW_TIMEFRAME,
  type OverviewTimeframe,
} from "@/features/dashboard/schemas";
import type { ProviderScope } from "@/features/providers/schemas";

export function useDashboard(
  timeframe: OverviewTimeframe = DEFAULT_OVERVIEW_TIMEFRAME,
  provider: ProviderScope = "all",
) {
  return useQuery({
    queryKey: ["dashboard", "overview", timeframe, provider],
    queryFn: () => getDashboardOverview({ timeframe, provider }),
    refetchInterval: 30_000,
    refetchIntervalInBackground: false,
    refetchOnWindowFocus: true,
  });
}

export function useDashboardProjections(provider: ProviderScope = "all", enabled = true) {
  return useQuery({
    queryKey: ["dashboard", "projections", provider],
    queryFn: () => getDashboardProjections(provider),
    enabled,
    refetchInterval: 30_000,
    refetchIntervalInBackground: false,
    refetchOnWindowFocus: true,
  });
}

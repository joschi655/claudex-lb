import { Badge } from "@/components/ui/badge";
import { cn } from "@/lib/utils";
import { PROVIDER_ANTHROPIC, PROVIDER_LABELS } from "@/utils/constants";

export type ProviderBadgeProps = {
  provider: string | null | undefined;
  className?: string;
};

/**
 * OpenAI is the unmarked default and Claude carries the badge, so a deployment
 * that only serves Codex looks exactly as it did before providers were split.
 */
export function ProviderBadge({ provider, className }: ProviderBadgeProps) {
  if (provider !== PROVIDER_ANTHROPIC) {
    return null;
  }

  return (
    <Badge
      variant="outline"
      className={cn(
        "shrink-0 border-orange-300 bg-orange-50 px-1.5 text-[10px] text-orange-700 dark:border-orange-500/30 dark:bg-orange-500/10 dark:text-orange-300",
        className,
      )}
    >
      {PROVIDER_LABELS[PROVIDER_ANTHROPIC]}
    </Badge>
  );
}

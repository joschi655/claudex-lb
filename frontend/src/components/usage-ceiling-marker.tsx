import { useEffect, useState } from "react";

import { Badge } from "@/components/ui/badge";
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from "@/components/ui/tooltip";
import { isAtUsageCeiling, usageCeilingMarkerPosition } from "@/utils/usage-ceiling";

type UsageCeilingMarkerProps = {
  label: string;
  ceilingPct?: number | null;
};

export function UsageCeilingMarker({ label, ceilingPct }: UsageCeilingMarkerProps) {
  const position = usageCeilingMarkerPosition(ceilingPct);
  if (position === null) return null;

  return (
    <span
      aria-hidden="true"
      title={`${label} ceiling at ${ceilingPct}% used`}
      data-testid="usage-ceiling-marker"
      className="pointer-events-none absolute top-1/2 h-3 w-px -translate-y-1/2 bg-foreground/60"
      style={{ left: `${position}%` }}
    />
  );
}

export function UsageCeilingBadge({
  label,
  ceilingPct,
  remainingPercent,
  resetAt,
}: UsageCeilingMarkerProps & {
  remainingPercent: number | null;
  resetAt?: string | null;
}) {
  const [now, setNow] = useState(() => Date.now());
  const atCeiling = isAtUsageCeiling({ remainingPercent, ceilingPct, resetAt, now });

  useEffect(() => {
    const resetTime = resetAt == null ? NaN : Date.parse(resetAt);
    if (!atCeiling || !Number.isFinite(resetTime)) return;

    const timeout = window.setTimeout(
      () => setNow(Date.now()),
      Math.min(2_147_483_647, Math.max(0, resetTime - Date.now())),
    );
    return () => window.clearTimeout(timeout);
  }, [atCeiling, resetAt, now]);

  if (!atCeiling) return null;

  const description = `${label} usage reached this account's ${ceilingPct}% ceiling. It is skipped until the window resets.`;

  return (
    <TooltipProvider>
      <Tooltip>
        <TooltipTrigger asChild>
          <Badge
            variant="outline"
            title={description}
            aria-label={description}
            className="shrink-0 border-amber-300 bg-amber-50 px-1.5 text-[10px] text-amber-700 dark:border-amber-500/30 dark:bg-amber-500/10 dark:text-amber-300"
          >
            At ceiling
          </Badge>
        </TooltipTrigger>
        <TooltipContent>{description}</TooltipContent>
      </Tooltip>
    </TooltipProvider>
  );
}

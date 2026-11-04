export function usageCeilingMarkerPosition(ceilingPct: number | null | undefined): number | null {
  if (typeof ceilingPct !== "number" || !Number.isFinite(ceilingPct) || ceilingPct <= 0 || ceilingPct > 100) {
    return null;
  }
  return 100 - ceilingPct;
}

export function isAtUsageCeiling({
  remainingPercent,
  ceilingPct,
  resetAt,
  now,
}: {
  remainingPercent: number | null | undefined;
  ceilingPct: number | null | undefined;
  resetAt?: string | null;
  now: number;
}): boolean {
  if (usageCeilingMarkerPosition(ceilingPct) === null || typeof ceilingPct !== "number") {
    return false;
  }
  if (typeof remainingPercent !== "number" || !Number.isFinite(remainingPercent)) {
    return false;
  }
  if (resetAt != null && Date.parse(resetAt) <= now) {
    return false;
  }
  return 100 - remainingPercent >= ceilingPct;
}

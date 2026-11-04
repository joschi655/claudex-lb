import { describe, expect, it } from "vitest";

import { isAtUsageCeiling, usageCeilingMarkerPosition } from "@/utils/usage-ceiling";

const now = Date.parse("2026-01-01T12:00:00Z");

describe("isAtUsageCeiling", () => {
  it.each([
    { remainingPercent: 11, expected: false },
    { remainingPercent: 10, expected: true },
    { remainingPercent: 5, expected: true },
    { remainingPercent: 50, expected: false },
    { remainingPercent: null, expected: false },
    { remainingPercent: undefined, expected: false },
    { remainingPercent: NaN, expected: false },
    { remainingPercent: Infinity, expected: false },
    { remainingPercent: -Infinity, expected: false },
  ])("returns $expected with $remainingPercent remaining at a 90% ceiling", ({ remainingPercent, expected }) => {
    expect(isAtUsageCeiling({ remainingPercent, ceilingPct: 90, now })).toBe(expected);
  });

  it.each([null, undefined, 0, -1, 101, NaN, Infinity, -Infinity])("ignores invalid ceiling %s", (ceilingPct) => {
    expect(isAtUsageCeiling({ remainingPercent: 0, ceilingPct, now })).toBe(false);
  });

  it.each([
    { resetAt: "2026-01-01T11:59:59Z", expected: false },
    { resetAt: "2026-01-01T12:00:00Z", expected: false },
    { resetAt: "2026-01-01T12:00:01Z", expected: true },
    { resetAt: "2026-01-01T13:00:00+01:00", expected: false },
    { resetAt: "invalid", expected: true },
    { resetAt: null, expected: true },
    { resetAt: undefined, expected: true },
  ])("returns $expected for reset time $resetAt", ({ resetAt, expected }) => {
    expect(isAtUsageCeiling({ remainingPercent: 5, ceilingPct: 90, resetAt, now })).toBe(expected);
  });

  it.each([
    { remainingPercent: 0, ceilingPct: 100, expected: true },
    { remainingPercent: 1, ceilingPct: 100, expected: false },
    { remainingPercent: 99, ceilingPct: 0.5, expected: true },
    { remainingPercent: 100, ceilingPct: 0.5, expected: false },
  ])("supports ceiling $ceilingPct with $remainingPercent remaining", ({ remainingPercent, ceilingPct, expected }) => {
    expect(isAtUsageCeiling({ remainingPercent, ceilingPct, now })).toBe(expected);
  });
});

describe("usageCeilingMarkerPosition", () => {
  it.each([
    { ceilingPct: 90, expected: 10 },
    { ceilingPct: 100, expected: 0 },
    { ceilingPct: 0.5, expected: 99.5 },
    { ceilingPct: 50, expected: 50 },
  ])("places a $ceilingPct% used ceiling at $expected% remaining", ({ ceilingPct, expected }) => {
    expect(usageCeilingMarkerPosition(ceilingPct)).toBe(expected);
  });

  it.each([null, undefined, 0, -1, 101, NaN, Infinity, -Infinity])("omits invalid ceiling %s", (ceilingPct) => {
    expect(usageCeilingMarkerPosition(ceilingPct)).toBeNull();
  });
});

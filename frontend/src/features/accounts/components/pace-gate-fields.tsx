import { useEffect, useState } from "react";
import { Gauge } from "lucide-react";

import { Input } from "@/components/ui/input";
import type {
  AccountPaceGatesUpdate,
  AccountSummary,
} from "@/features/accounts/schemas";

export type PaceGateFieldsProps = {
  account: AccountSummary;
  busy: boolean;
  readOnly?: boolean;
  onChange: (accountId: string, gates: AccountPaceGatesUpdate) => void;
};

type GateKey = keyof AccountPaceGatesUpdate;

const GATES: {
  key: GateKey;
  label: string;
  hint: string;
  unit: string;
  max: number;
  step: number;
}[] = [
  {
    key: "paceMarginPrimaryPct",
    label: "5h pace margin",
    hint: "Serve only while 5h usage sits this many points below the even-pace line.",
    unit: "%",
    max: 100,
    step: 1,
  },
  {
    key: "paceMarginSecondaryPct",
    label: "Weekly pace margin",
    hint: "The same test against the weekly window.",
    unit: "%",
    max: 100,
    step: 1,
  },
  {
    key: "preResetWindowMinutes",
    label: "Pre-reset window",
    hint: "Serve only inside this many minutes before the 5h reset.",
    unit: "min",
    max: 10080,
    step: 5,
  },
];

/**
 * Per-account pace gates, editable from the dashboard.
 *
 * An empty field means the gate is off, which is a different state from zero: a
 * margin of `0` gates exactly at the pace line, while no margin at all never
 * gates. The API distinguishes them the same way — an omitted field leaves a
 * gate alone, an explicit null clears it — so each field commits on blur and
 * sends only itself.
 */
export function PaceGateFields({
  account,
  busy,
  readOnly = false,
  onChange,
}: PaceGateFieldsProps) {
  return (
    <div className="space-y-2 rounded-md border bg-muted/30 p-3">
      <div className="flex items-center gap-2 text-sm font-medium">
        <Gauge className="h-4 w-4 text-muted-foreground" />
        Pace gates
      </div>
      <p className="text-xs text-muted-foreground">
        Bound how fast this account is drawn from. Leave a field empty to switch
        that gate off. A pinned account ignores all three while it is pinned.
      </p>
      <div className="grid gap-2 sm:grid-cols-3">
        {GATES.map((gate) => (
          <PaceGateField
            key={gate.key}
            account={account}
            gate={gate}
            busy={busy}
            readOnly={readOnly}
            onChange={onChange}
          />
        ))}
      </div>
    </div>
  );
}

function PaceGateField({
  account,
  gate,
  busy,
  readOnly,
  onChange,
}: {
  account: AccountSummary;
  gate: (typeof GATES)[number];
  busy: boolean;
  readOnly: boolean;
  onChange: (accountId: string, gates: AccountPaceGatesUpdate) => void;
}) {
  const stored = account[gate.key] ?? null;
  const [draft, setDraft] = useState(stored === null ? "" : String(stored));

  // A refetch after a save (or a change made from the menu bar) is the source of
  // truth; re-seed the field from it unless the operator is mid-edit.
  useEffect(() => {
    setDraft(stored === null ? "" : String(stored));
  }, [stored]);

  const inputId = `${gate.key}-${account.accountId}`;
  const commit = () => {
    const trimmed = draft.trim();
    const next = trimmed === "" ? null : Number(trimmed);
    if (next !== null && (!Number.isFinite(next) || next < 0 || next > gate.max)) {
      setDraft(stored === null ? "" : String(stored));
      return;
    }
    if (next === stored) return;
    onChange(account.accountId, { [gate.key]: next });
  };

  return (
    <div className="min-w-0 space-y-1">
      <label
        htmlFor={inputId}
        className="block truncate text-xs font-medium"
        title={gate.hint}
      >
        {gate.label}
      </label>
      <div className="flex items-center gap-1.5">
        <Input
          id={inputId}
          type="number"
          inputMode="numeric"
          min={0}
          max={gate.max}
          step={gate.step}
          placeholder="off"
          className="h-8 min-w-0 text-xs"
          value={draft}
          disabled={busy || readOnly}
          onChange={(event) => setDraft(event.target.value)}
          onBlur={commit}
          onKeyDown={(event) => {
            if (event.key === "Enter") event.currentTarget.blur();
          }}
        />
        <span className="shrink-0 text-xs text-muted-foreground">
          {gate.unit}
        </span>
      </div>
    </div>
  );
}

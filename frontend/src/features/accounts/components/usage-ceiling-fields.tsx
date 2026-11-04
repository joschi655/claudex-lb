import { useState } from "react";
import { ShieldAlert } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import type { PaceGateFieldsProps } from "@/features/accounts/components/pace-gate-fields";

type CeilingKey = "usageCeilingPrimaryPct" | "usageCeilingSecondaryPct";

const CEILINGS: { key: CeilingKey; label: string }[] = [
  { key: "usageCeilingPrimaryPct", label: "5h ceiling" },
  { key: "usageCeilingSecondaryPct", label: "Weekly ceiling" },
];
const PRESETS = [null, 80, 90, 95] as const;

export function UsageCeilingFields(props: PaceGateFieldsProps) {
  return (
    <div className="space-y-2 rounded-md border bg-muted/30 p-3">
      <div className="flex items-center gap-2 text-sm font-medium">
        <ShieldAlert className="h-4 w-4 text-muted-foreground" />
        Usage ceiling
      </div>
      <p className="text-xs text-muted-foreground">
        Stop serving from this account once a window reaches this usage and leave
        the rest for its owner. Applies even while pinned.
      </p>
      <div className="grid gap-2 sm:grid-cols-2">
        {CEILINGS.map((ceiling) => (
          <UsageCeilingField key={ceiling.key} {...props} ceiling={ceiling} />
        ))}
      </div>
    </div>
  );
}

function UsageCeilingField({
  account,
  busy,
  readOnly = false,
  onChange,
  ceiling,
}: PaceGateFieldsProps & { ceiling: (typeof CEILINGS)[number] }) {
  const stored = account[ceiling.key] ?? null;
  const [draft, setDraft] = useState(stored === null ? "" : String(stored));
  const [seeded, setSeeded] = useState(stored);

  if (seeded !== stored) {
    setSeeded(stored);
    setDraft(stored === null ? "" : String(stored));
  }

  const disabled = busy || readOnly;
  const inputId = `${ceiling.key}-${account.accountId}`;
  const commitValue = (next: number | null) => {
    if (disabled) return;
    setDraft(next === null ? "" : String(next));
    if (next === stored) return;
    onChange(account.accountId, { [ceiling.key]: next });
  };
  const commitDraft = (badInput: boolean) => {
    const trimmed = draft.trim();
    const next = trimmed === "" ? null : Number(trimmed);
    if (badInput || (next !== null && (!Number.isFinite(next) || next <= 0 || next > 100))) {
      setDraft(stored === null ? "" : String(stored));
      return;
    }
    commitValue(next);
  };

  return (
    <div className="min-w-0 space-y-1">
      <label htmlFor={inputId} className="block text-xs font-medium">
        {ceiling.label}
      </label>
      <div className="flex items-center gap-1.5">
        <Input
          id={inputId}
          type="number"
          inputMode="decimal"
          min={0}
          max={100}
          step="any"
          placeholder="off"
          className="h-8 min-w-0 text-xs"
          value={draft}
          disabled={disabled}
          onChange={(event) => setDraft(event.target.value)}
          onBlur={(event) => commitDraft(event.currentTarget.validity.badInput)}
          onKeyDown={(event) => {
            if (event.key === "Enter") event.currentTarget.blur();
          }}
        />
        <span className="shrink-0 text-xs text-muted-foreground">%</span>
      </div>
      <div className="flex gap-1" role="group" aria-label={`${ceiling.label} presets`}>
        {PRESETS.map((preset) => (
          <Button
            key={preset ?? "off"}
            type="button"
            size="sm"
            variant="ghost"
            className="h-6 px-2 text-xs aria-pressed:bg-muted"
            aria-pressed={stored === preset}
            disabled={disabled}
            onMouseDown={(event) => event.preventDefault()}
            onClick={() => commitValue(preset)}
          >
            {preset ?? "Off"}
          </Button>
        ))}
      </div>
    </div>
  );
}

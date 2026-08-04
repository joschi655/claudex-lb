import { useRef, type KeyboardEvent } from "react";

import type { ProviderScope } from "@/features/providers/schemas";
import { cn } from "@/lib/utils";

const PROVIDER_OPTIONS: ReadonlyArray<{ value: ProviderScope; label: string }> = [
  { value: "all", label: "All" },
  { value: "openai", label: "OpenAI" },
  { value: "anthropic", label: "Claude" },
];

export type ProviderScopeControlProps = {
  value: ProviderScope;
  onChange: (value: ProviderScope) => void;
};

export function ProviderScopeControl({ value, onChange }: ProviderScopeControlProps) {
  const buttonRefs = useRef<Array<HTMLButtonElement | null>>([]);

  const handleKeyDown = (event: KeyboardEvent<HTMLButtonElement>, index: number) => {
    let nextIndex: number | null = null;
    if (event.key === "ArrowRight" || event.key === "ArrowDown") {
      nextIndex = (index + 1) % PROVIDER_OPTIONS.length;
    } else if (event.key === "ArrowLeft" || event.key === "ArrowUp") {
      nextIndex = (index - 1 + PROVIDER_OPTIONS.length) % PROVIDER_OPTIONS.length;
    } else if (event.key === "Home") {
      nextIndex = 0;
    } else if (event.key === "End") {
      nextIndex = PROVIDER_OPTIONS.length - 1;
    }
    if (nextIndex === null) {
      return;
    }
    event.preventDefault();
    onChange(PROVIDER_OPTIONS[nextIndex].value);
    buttonRefs.current[nextIndex]?.focus();
  };

  return (
    <div
      role="radiogroup"
      aria-label="Provider scope"
      className="inline-flex h-8 shrink-0 items-center rounded-md border bg-muted/40 p-0.5"
    >
      {PROVIDER_OPTIONS.map((option, index) => (
        <button
          key={option.value}
          ref={(element) => {
            buttonRefs.current[index] = element;
          }}
          type="button"
          role="radio"
          aria-checked={value === option.value}
          tabIndex={value === option.value ? 0 : -1}
          onClick={() => onChange(option.value)}
          onKeyDown={(event) => handleKeyDown(event, index)}
          className={cn(
            "h-7 min-w-14 rounded px-2.5 text-xs font-medium transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-1",
            value === option.value
              ? "bg-background text-foreground shadow-sm"
              : "text-muted-foreground hover:text-foreground",
          )}
        >
          {option.label}
        </button>
      ))}
    </div>
  );
}

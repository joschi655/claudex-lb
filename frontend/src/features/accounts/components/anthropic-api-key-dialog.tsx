import { useState } from "react";
import { KeyRound } from "lucide-react";

import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { AnthropicApiKeyRequestSchema, type AnthropicApiKeyRequest } from "@/features/accounts/schemas";

export type AnthropicApiKeyDialogProps = {
  open: boolean;
  mode: "create" | "replace";
  initialLabel?: string;
  busy: boolean;
  onOpenChange: (open: boolean) => void;
  onSubmit: (payload: AnthropicApiKeyRequest) => Promise<void>;
};

type AnthropicApiKeyFormProps = Omit<AnthropicApiKeyDialogProps, "open" | "onOpenChange"> & {
  onClose: () => void;
};

function AnthropicApiKeyForm({
  mode,
  initialLabel = "",
  busy,
  onClose,
  onSubmit,
}: AnthropicApiKeyFormProps) {
  const [label, setLabel] = useState(initialLabel);
  const [apiKey, setApiKey] = useState("");
  const [validationError, setValidationError] = useState<string | null>(null);

  const handleSubmit = async (event: React.FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const parsed = AnthropicApiKeyRequestSchema.safeParse({ label, apiKey });
    if (!parsed.success) {
      setValidationError("Enter a label and Anthropic Console API key.");
      return;
    }
    setValidationError(null);
    try {
      await onSubmit(parsed.data);
    } catch {
      return;
    }
    onClose();
  };

  return (
    <form className="space-y-4" onSubmit={handleSubmit}>
      <div className="space-y-2">
        <Label htmlFor="anthropic-account-label">Label</Label>
        <Input
          id="anthropic-account-label"
          value={label}
          maxLength={100}
          autoComplete="off"
          placeholder="Production Claude"
          disabled={busy}
          onChange={(event) => setLabel(event.target.value)}
        />
      </div>
      <div className="space-y-2">
        <Label htmlFor="anthropic-api-key">Anthropic API key</Label>
        <Input
          id="anthropic-api-key"
          type="password"
          value={apiKey}
          autoComplete="new-password"
          spellCheck={false}
          placeholder="sk-ant-api03-..."
          disabled={busy}
          onChange={(event) => setApiKey(event.target.value)}
        />
      </div>
      {validationError ? (
        <p className="text-xs text-destructive" role="alert">
          {validationError}
        </p>
      ) : null}
      <DialogFooter>
        <Button type="button" variant="outline" disabled={busy} onClick={onClose}>
          Cancel
        </Button>
        <Button type="submit" disabled={busy}>
          <KeyRound className="h-4 w-4" />
          {mode === "create" ? "Add key" : "Replace key"}
        </Button>
      </DialogFooter>
    </form>
  );
}

export function AnthropicApiKeyDialog({
  open,
  mode,
  initialLabel,
  busy,
  onOpenChange,
  onSubmit,
}: AnthropicApiKeyDialogProps) {
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      {open ? (
        <DialogContent>
          <DialogHeader>
            <DialogTitle>{mode === "create" ? "Add Claude account" : "Replace Claude API key"}</DialogTitle>
            <DialogDescription>
              Use an Anthropic Console API key. Claude.ai subscription credentials are not supported.
            </DialogDescription>
          </DialogHeader>
          <AnthropicApiKeyForm
            mode={mode}
            initialLabel={initialLabel}
            busy={busy}
            onClose={() => onOpenChange(false)}
            onSubmit={onSubmit}
          />
        </DialogContent>
      ) : null}
    </Dialog>
  );
}

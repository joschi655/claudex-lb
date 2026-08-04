import { z } from "zod";

export const AccountProviderSchema = z.enum(["openai", "anthropic"]);
export const ProviderScopeSchema = z.enum(["all", "openai", "anthropic"]);

export type AccountProvider = z.infer<typeof AccountProviderSchema>;
export type ProviderScope = z.infer<typeof ProviderScopeSchema>;

export const DEFAULT_PROVIDER_SCOPE: ProviderScope = "all";

export function parseProviderScope(value: string | null | undefined): ProviderScope {
  const parsed = ProviderScopeSchema.safeParse(value);
  return parsed.success ? parsed.data : DEFAULT_PROVIDER_SCOPE;
}

import { del, get, patch, post, put } from "@/lib/api-client";

import {
  ApiKeyAccountRoutingRulesUpdateRequestSchema,
  ApiKeyCreateRequestSchema,
  ApiKeyCreateResponseSchema,
  ApiKeyListSchema,
  ApiKeySchema,
  ApiKeyUpdateRequestSchema,
  ModelsResponseSchema,
} from "@/features/api-keys/schemas";

export const API_KEYS_BASE_PATH = "/api/api-keys";
const MODELS_PATH = "/api/models";

export function listApiKeys() {
  return get(`${API_KEYS_BASE_PATH}/`, ApiKeyListSchema);
}

export function createApiKey(payload: unknown) {
  const validated = ApiKeyCreateRequestSchema.parse(payload);
  return post(`${API_KEYS_BASE_PATH}/`, ApiKeyCreateResponseSchema, {
    body: validated,
  });
}

export function updateApiKey(keyId: string, payload: unknown) {
  const validated = ApiKeyUpdateRequestSchema.parse(payload);
  return patch(`${API_KEYS_BASE_PATH}/${encodeURIComponent(keyId)}`, ApiKeySchema, {
    body: validated,
  });
}

export function replaceApiKeyAccountRoutingRules(keyId: string, payload: unknown) {
  const validated = ApiKeyAccountRoutingRulesUpdateRequestSchema.parse(payload);
  return put(
    `${API_KEYS_BASE_PATH}/${encodeURIComponent(keyId)}/account-routing-rules`,
    ApiKeySchema,
    { body: validated },
  );
}

export function deleteApiKey(keyId: string) {
  return del(`${API_KEYS_BASE_PATH}/${encodeURIComponent(keyId)}`);
}

export function regenerateApiKey(keyId: string) {
  return post(
    `${API_KEYS_BASE_PATH}/${encodeURIComponent(keyId)}/regenerate`,
    ApiKeyCreateResponseSchema,
  );
}

export function listModels() {
  return get(MODELS_PATH, ModelsResponseSchema);
}

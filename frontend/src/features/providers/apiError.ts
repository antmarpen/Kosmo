import type { KosmoError } from "@/components/KosmoErrorAlert";

/**
 * Shared API-contract helpers for the providers feature. The backend returns
 * flat KosmoError bodies (`{ code, message_key, params, details }`) and
 * openapi-fetch exposes them as `result.error`; the helpers below keep that
 * contract in one place so every provider surface localizes failures the
 * same way. (`ProviderWizard` predates this module and carries its own copy.)
 */

/** Unwraps an openapi-fetch result, throwing the error body on failure. */
export function unwrap<T>(result: { data?: T; error?: unknown }): T {
  if (result.error || result.data === undefined) throw result.error ?? new Error("Empty API response");
  return result.data;
}

/**
 * Normalizes thrown API failures into a KosmoError so localized message keys
 * are never masked by the generic fallback.
 */
export function toKosmoError(cause: unknown): KosmoError {
  // Backend error bodies are flat ({ code, message_key, params, details }).
  const raw = cause as { error?: KosmoError; code?: string; message_key?: string; params?: Record<string, unknown> } | undefined;
  if (raw?.error) return raw.error;
  if (raw?.message_key) return { code: raw.code ?? "PROVIDER_REQUEST_FAILED", message_key: raw.message_key, params: raw.params };
  return { code: "PROVIDER_REQUEST_FAILED", message_key: "errors.generic" };
}

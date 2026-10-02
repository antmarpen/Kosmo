import type { KosmoError } from "@/components/KosmoErrorAlert";

/**
 * Shared API-contract helpers for openapi-fetch surfaces. The backend returns
 * flat KosmoError bodies (`{ code, message_key, params, details }`) and
 * openapi-fetch exposes them as `result.error`; these helpers keep that
 * normalization in one place so every surface localizes failures the same way.
 */

/** Unwraps an openapi-fetch result, throwing the error body on failure. */
export function unwrap<T>(result: { data?: T; error?: unknown }): T {
  if (result.error || result.data === undefined) throw result.error ?? new Error("Empty API response");
  return result.data;
}

/**
 * Normalizes thrown API failures into a KosmoError so localized message keys
 * are never masked by the generic fallback. `fallbackCode` names the calling
 * surface in the code of an unrecognizable failure (the message key still
 * localizes it).
 */
export function toKosmoError(cause: unknown, fallbackCode: string): KosmoError {
  const raw = cause as { error?: KosmoError; code?: string; message_key?: string; params?: Record<string, unknown>; details?: KosmoError["details"] } | undefined;
  if (raw?.error) return raw.error;
  if (raw?.message_key) return { code: raw.code ?? fallbackCode, message_key: raw.message_key, params: raw.params, details: raw.details };
  return { code: fallbackCode, message_key: "errors.generic" };
}

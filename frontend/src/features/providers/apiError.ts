import { toKosmoError as normalizeError, unwrap } from "@/api/apiError";
import type { KosmoError } from "@/components/KosmoErrorAlert";

/**
 * Shared API-contract helpers for the providers feature. Normalization lives
 * in `@/api/apiError`; this module binds the provider fallback code so every
 * provider surface localizes failures the same way.
 */

/** Unwraps an openapi-fetch result, throwing the error body on failure. */
export { unwrap };

/** Normalizes thrown API failures into a KosmoError with the provider fallback code. */
export function toKosmoError(cause: unknown): KosmoError {
  return normalizeError(cause, "PROVIDER_REQUEST_FAILED");
}

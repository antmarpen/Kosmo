import { parse as parseJsonc, type ParseError } from "jsonc-parser";

export type Config = Record<string, unknown>;

/**
 * Mirrors the backend `MAX_CONFIG_BYTES` limit (app/api/routes/provider_configs.py)
 * so oversized uploads fail fast in the browser with a localized error.
 */
export const MAX_PROVIDER_FILE_BYTES = 1_000_000;

export type ProviderFileFailure =
  | { reason: "unsupported_type"; filename: string }
  | { reason: "too_large"; filename: string }
  | { reason: "read_failed"; filename: string }
  | { reason: "invalid_json"; filename: string };

export type ProviderFileRead =
  | { ok: true; filename: string; text: string; value: Config }
  | { ok: false; failure: ProviderFileFailure };

const SUPPORTED_EXTENSIONS = [".json", ".jsonc"];

/**
 * Only .json and .jsonc are accepted. Notably .js/.mjs/.cjs are rejected:
 * they are scripts, not configuration, and must never be parsed as config.
 */
export function isSupportedConfigFile(filename: string): boolean {
  const lower = filename.toLowerCase();
  return SUPPORTED_EXTENSIONS.some((extension) => lower.endsWith(extension));
}

/**
 * Parses JSON or JSONC text (comments and trailing commas allowed) into a
 * plain object. Uses the vetted `jsonc-parser` (VS Code) — never regex or
 * eval — and rejects non-object roots. Returns null for anything invalid.
 */
export function parseConfigObject(text: string): Config | null {
  const errors: ParseError[] = [];
  let parsed: unknown;
  try {
    parsed = parseJsonc(text, errors, { allowTrailingComma: true });
  } catch {
    return null;
  }
  if (errors.length > 0) return null;
  if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) return null;
  return parsed as Config;
}

/**
 * Serializes a parsed configuration back to strict JSON. JSONC input is
 * normalized here, so the wire payload always satisfies the backend's
 * strict `json.loads` contract.
 */
export function serializeProviderConfig(value: Config): string {
  return JSON.stringify(value);
}

/**
 * Reads a provider configuration or credentials file with the guards the
 * upload contract needs: extension allow-list, size limit, read-failure
 * capture, and JSON(C) object parsing.
 */
export async function readProviderFile(file: File): Promise<ProviderFileRead> {
  const { name } = file;
  if (!isSupportedConfigFile(name)) return { ok: false, failure: { reason: "unsupported_type", filename: name } };
  if (file.size > MAX_PROVIDER_FILE_BYTES) return { ok: false, failure: { reason: "too_large", filename: name } };
  let text: string;
  try {
    text = await file.text();
  } catch {
    return { ok: false, failure: { reason: "read_failed", filename: name } };
  }
  const value = parseConfigObject(text);
  if (!value) return { ok: false, failure: { reason: "invalid_json", filename: name } };
  return { ok: true, filename: name, text, value };
}

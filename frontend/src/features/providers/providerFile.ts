import { parse as parseJsonc, type ParseError } from "jsonc-parser";

export type Config = Record<string, unknown>;
export type AuthCredential = {
  id: string;
  integrationID: string;
  label: string;
  active: boolean;
  value: { type: "key"; key: string };
};

/**
 * Mirrors the backend `MAX_CONFIG_BYTES` limit (app/api/routes/provider_configs.py)
 * so oversized uploads fail fast in the browser with a localized error.
 */
export const MAX_PROVIDER_FILE_BYTES = 1_000_000;

export type ProviderFileFailure =
  | { reason: "unsupported_type"; filename: string }
  | { reason: "too_large"; filename: string }
  | { reason: "read_failed"; filename: string }
  | { reason: "invalid_json"; filename: string }
  | { reason: "invalid_auth"; filename: string }
  | { reason: "unsupported_auth"; filename: string };

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
  const config = parsed as Record<string, unknown>;
  if ("provider" in config || !config.providers || typeof config.providers !== "object" || Array.isArray(config.providers)) return null;
  return parsed as Config;
}

/** Parse the native v2 auth import array; OAuth and unknown credential kinds are unsupported. */
export function parseAuthArray(text: string): AuthCredential[] | null {
  const errors: ParseError[] = [];
  let parsed: unknown;
  try { parsed = parseJsonc(text, errors, { allowTrailingComma: true }); } catch { return null; }
  if (errors.length || !Array.isArray(parsed)) return null;
  for (const item of parsed) {
    if (!item || typeof item !== "object" || Array.isArray(item)) return null;
    const credential = item as Record<string, unknown>;
    const value = credential.value;
    if (Object.keys(credential).sort().join(",") !== "active,id,integrationID,label,value"
      || typeof credential.id !== "string" || !credential.id
      || typeof credential.integrationID !== "string" || !credential.integrationID
      || typeof credential.label !== "string" || !credential.label
      || typeof credential.active !== "boolean"
      || !value || typeof value !== "object" || Array.isArray(value)) return null;
    const authValue = value as Record<string, unknown>;
    if (Object.keys(authValue).sort().join(",") !== "key,type" || authValue.type !== "key"
      || typeof authValue.key !== "string" || !authValue.key) return null;
  }
  return parsed as AuthCredential[];
}

/**
 * Serializes a parsed configuration back to strict JSON. JSONC input is
 * normalized here, so the wire payload always satisfies the backend's
 * strict `json.loads` contract.
 */
export function serializeProviderConfig(value: Config | AuthCredential[]): string {
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

export async function readProviderAuthFile(file: File): Promise<
  | { ok: true; filename: string; text: string; value: AuthCredential[] }
  | { ok: false; failure: ProviderFileFailure }
> {
  const { name } = file;
  if (!isSupportedConfigFile(name)) return { ok: false, failure: { reason: "unsupported_type", filename: name } };
  if (file.size > MAX_PROVIDER_FILE_BYTES) return { ok: false, failure: { reason: "too_large", filename: name } };
  let text: string;
  try { text = await file.text(); } catch { return { ok: false, failure: { reason: "read_failed", filename: name } }; }
  const value = parseAuthArray(text);
  if (value) return { ok: true, filename: name, text, value };
  const errors: ParseError[] = [];
  let parsed: unknown;
  try { parsed = parseJsonc(text, errors, { allowTrailingComma: true }); } catch { parsed = undefined; }
  let reason: ProviderFileFailure["reason"] = "invalid_json";
  if (!errors.length && Array.isArray(parsed)) {
    const hasUnsupportedMethod = parsed.some((item) => item && typeof item === "object" && !Array.isArray(item)
      && (item as Record<string, unknown>).value && typeof (item as Record<string, unknown>).value === "object"
      && ((item as Record<string, unknown>).value as Record<string, unknown>).type !== "key");
    reason = hasUnsupportedMethod ? "unsupported_auth" : "invalid_auth";
  }
  return { ok: false, failure: { reason, filename: name } };
}

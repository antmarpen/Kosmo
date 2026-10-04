/**
 * WP-14 — pure state and wire-shape model for MCP transport authoring.
 *
 * The client keeps named env/header entries as drafts and derives the exact
 * `EntryWrite` actions the backend contract requires:
 * - `replace` (with a value) for new entries, changed values, and any secret
 *   classification change;
 * - `keep` (never a value) only for a stored, set secret left untouched;
 *   a blank input therefore means retention, never blank replacement;
 * - `remove` (never a value) for an existing entry deleted in the form.
 *
 * The wire payload is always the exact desired entry set for the authored
 * transport kind, so switching stdio/http resets every field and entry —
 * old-kind entries cannot be expressed in the new collection and the whole
 * stored transport is replaced by the server. Secret values never round-trip:
 * stored secrets hydrate as an empty masked input plus an `is_set` marker.
 *
 * The generated schema types remain the assignability target: everything this
 * module emits is structurally compatible with the OpenAPI client contracts.
 */

export type McpTransportType = "stdio" | "http";
export type TransportEntryAction = "replace" | "keep" | "remove";
/**
 * The exact wire entry shape this screen emits. `value` is present only for
 * `replace` — `keep` and `remove` must never carry one. Structurally
 * assignable to the generated `EntryWrite`.
 */
export type TransportEntryWrite = {
  name: string;
  secret: boolean;
  action: TransportEntryAction;
  value?: string;
};
/**
 * The exact transport request this screen emits: the entry collection is
 * always present and is the desired set. Structurally assignable to the
 * generated `StdioTransport` / `HttpTransport`.
 */
export type TransportWrite =
  | { type: "stdio"; command: string; args: string[]; env: TransportEntryWrite[] }
  | { type: "http"; url: string; headers: TransportEntryWrite[] };

/** Structural subset of the MCP detail response used for hydration. */
export type TransportEntryDetail = {
  name: string;
  secret: boolean;
  is_set: boolean;
  value?: string | null;
};
/** Accepts readonly shapes so frozen fixtures and API responses both fit. */
export type TransportDetail =
  | { type: "stdio"; command: string; args: readonly string[]; env: readonly TransportEntryDetail[] }
  | { type: "http"; url: string; headers: readonly TransportEntryDetail[] };

export type TransportEntryDraft = {
  /** Client-only stable identity; never sent to the server. */
  id: string;
  name: string;
  secret: boolean;
  /**
   * Typed value. For a stored secret this starts empty: blank means "keep the
   * stored value", typing means "replace". Nonsecret values hydrate from the
   * detail response, which is allowed to carry them.
   */
  value: string;
  /** Whether the entry exists on the stored server (edit mode). */
  existing: boolean;
  /** Classification as loaded, to detect classification changes. */
  existingSecret: boolean;
  /** Presence marker as loaded (`is_set`); stored secrets may not be set. */
  existingIsSet: boolean;
  /** Loaded value for nonsecret entries, to detect edits. */
  initialValue: string;
};

export type TransportDraft = {
  type: McpTransportType;
  /** stdio: executable path/name without arguments. */
  command: string;
  /** stdio: one argument per line. */
  argsText: string;
  /** http: absolute http(s) URL without credentials. */
  url: string;
  entries: TransportEntryDraft[];
  /** Existing entries deleted in this editing session, sent as `remove`. */
  removals: Array<{ id: string; name: string; secret: boolean }>;
};

export type TransportEntryErrorCode = "name_invalid" | "name_duplicate" | "value_required";

export type TransportErrors = {
  /** stdio command empty or containing whitespace. */
  command?: boolean;
  /** http URL not absolute http(s) or carrying credentials. */
  url?: boolean;
  /** Per-entry validation failures keyed by draft id. */
  entries: Record<string, TransportEntryErrorCode[]>;
  /**
   * A rename would invalidate `keep` actions: stored secrets cannot be
   * retained across a server rename, so each kept secret needs a replacement
   * value or an explicit removal.
   */
  keepAfterRename?: boolean;
};

export type TransportBuildResult =
  | { ok: true; transport: TransportWrite }
  | { ok: false; errors: TransportErrors };

// Same name grammars the backend enforces (env identifier vs header token).
const ENV_NAME = /^[A-Za-z_][A-Za-z0-9_]*$/;
const HEADER_NAME = /^[!#$%&'*+.^_`|~0-9A-Za-z-]+$/;

let nextEntryCounter = 0;
function nextEntryId(): string {
  nextEntryCounter += 1;
  return `entry-${nextEntryCounter}`;
}

function emptyDraft(type: McpTransportType): TransportDraft {
  return { type, command: "", argsText: "", url: "", entries: [], removals: [] };
}

export function createTransportDraft(type: McpTransportType = "stdio"): TransportDraft {
  return emptyDraft(type);
}

export function transportFromDetail(detail: TransportDetail): TransportDraft {
  const draft = emptyDraft(detail.type);
  if (detail.type === "stdio") {
    draft.command = detail.command;
    draft.argsText = detail.args.join("\n");
    draft.entries = detail.env.map((item) => hydrateEntry(item));
  } else {
    draft.url = detail.url;
    draft.entries = detail.headers.map((item) => hydrateEntry(item));
  }
  return draft;
}

function hydrateEntry(item: TransportEntryDetail): TransportEntryDraft {
  const value = item.secret ? "" : (item.value ?? "");
  return {
    id: nextEntryId(),
    name: item.name,
    secret: item.secret,
    value,
    existing: true,
    existingSecret: item.secret,
    existingIsSet: item.is_set,
    initialValue: value,
  };
}

export function addEntryDraft(draft: TransportDraft, secret = false): TransportDraft {
  return {
    ...draft,
    entries: [
      ...draft.entries,
      {
        id: nextEntryId(),
        name: "",
        secret,
        value: "",
        existing: false,
        existingSecret: false,
        existingIsSet: false,
        initialValue: "",
      },
    ],
  };
}

export function updateEntryDraft(
  draft: TransportDraft,
  entryId: string,
  patch: Partial<Pick<TransportEntryDraft, "name" | "secret" | "value">>,
): TransportDraft {
  return {
    ...draft,
    entries: draft.entries.map((item) => (item.id === entryId ? { ...item, ...patch } : item)),
  };
}

export function removeEntryDraft(draft: TransportDraft, entryId: string): TransportDraft {
  const removed = draft.entries.find((item) => item.id === entryId);
  if (!removed) return draft;
  return {
    ...draft,
    entries: draft.entries.filter((item) => item.id !== entryId),
    removals: removed.existing
      ? // The stored classification is the one a `remove` must repeat, even if
        // the user flipped the switch before deleting the row.
        [...draft.removals, { id: removed.id, name: removed.name, secret: removed.existingSecret }]
      : draft.removals,
  };
}

export function switchTransport(_draft: TransportDraft, next: McpTransportType): TransportDraft {
  // Incompatible fields are destroyed: the entry collection of the other kind
  // cannot express them, and the server replaces the whole stored transport.
  // Nothing from the previous draft survives, hence the unused draft.
  return emptyDraft(next);
}

export function transportHasContent(draft: TransportDraft): boolean {
  return (
    draft.command.trim() !== "" ||
    draft.argsText.trim() !== "" ||
    draft.url.trim() !== "" ||
    draft.entries.length > 0
  );
}

/** Duplicate detection matches the backend: exact for env, folded for headers. */
function entryKey(kind: McpTransportType, name: string): string {
  return kind === "http" ? name.toLowerCase() : name;
}

function deriveEntry(
  item: TransportEntryDraft,
  kind: McpTransportType,
  errors: TransportErrors,
): TransportEntryWrite | null {
  const entryErrors: TransportEntryErrorCode[] = [];
  const name = item.name.trim();
  const namePattern = kind === "stdio" ? ENV_NAME : HEADER_NAME;
  if (!namePattern.test(name)) entryErrors.push("name_invalid");

  // A stored, set secret left untouched (blank masked input) is the only
  // keep; everything else is an explicit replacement that needs a value.
  const canKeep =
    item.existing && item.secret && item.existingSecret && item.existingIsSet && item.value === "";
  const action: TransportEntryAction = canKeep ? "keep" : "replace";
  if (action === "replace" && item.value.length === 0) entryErrors.push("value_required");

  if (entryErrors.length > 0) {
    errors.entries[item.id] = entryErrors;
    return null;
  }
  if (action === "keep") return { name, secret: true, action: "keep" };
  return { name, secret: item.secret, action: "replace", value: item.value };
}

export function buildTransportPayload(
  draft: TransportDraft,
  options: { nameChanged: boolean },
): TransportBuildResult {
  const kind = draft.type;
  const errors: TransportErrors = { entries: {} };
  const keeps: string[] = [];

  if (kind === "stdio") {
    const command = draft.command.trim();
    if (command.length === 0 || /\s/.test(command)) errors.command = true;
  } else {
    const url = draft.url.trim();
    let validUrl = false;
    try {
      const parsed = new URL(url);
      validUrl =
        (parsed.protocol === "http:" || parsed.protocol === "https:") &&
        parsed.username === "" &&
        parsed.password === "" &&
        parsed.hostname !== "";
    } catch {
      validUrl = false;
    }
    if (!validUrl) errors.url = true;
  }

  const writes: TransportEntryWrite[] = [];
  for (const item of draft.entries) {
    const write = deriveEntry(item, kind, errors);
    if (write === null) continue;
    if (write.action === "keep") keeps.push(item.id);
    writes.push(write);
  }

  // Every copy of a duplicated name is flagged, mirroring the backend reject.
  const counts = new Map<string, number>();
  for (const item of draft.entries) {
    const key = entryKey(kind, item.name);
    counts.set(key, (counts.get(key) ?? 0) + 1);
  }
  if (counts.size !== draft.entries.length) {
    for (const item of draft.entries) {
      if ((counts.get(entryKey(kind, item.name)) ?? 0) > 1) {
        const list = errors.entries[item.id] ?? [];
        if (!list.includes("name_duplicate")) list.push("name_duplicate");
        errors.entries[item.id] = list;
      }
    }
  }

  // The server rejects `keep` after a rename; surface that before submitting.
  if (options.nameChanged && keeps.length > 0) {
    errors.keepAfterRename = true;
    for (const id of keeps) {
      const list = errors.entries[id] ?? [];
      if (!list.includes("value_required")) list.push("value_required");
      errors.entries[id] = list;
    }
  }

  const hasErrors =
    errors.command === true ||
    errors.url === true ||
    errors.keepAfterRename === true ||
    Object.keys(errors.entries).length > 0;
  if (hasErrors) return { ok: false, errors };

  const currentNames = new Set(draft.entries.map((item) => entryKey(kind, item.name)));
  const removalWrites: TransportEntryWrite[] = draft.removals
    .filter((removal) => !currentNames.has(entryKey(kind, removal.name)))
    .map((removal) => ({ name: removal.name, secret: removal.secret, action: "remove" as const }));

  const allWrites = [...writes, ...removalWrites];
  if (kind === "stdio") {
    const args = draft.argsText
      .split("\n")
      .filter((line) => line.trim().length > 0);
    return {
      ok: true,
      transport: { type: "stdio", command: draft.command.trim(), args, env: allWrites },
    };
  }
  return { ok: true, transport: { type: "http", url: draft.url.trim(), headers: allWrites } };
}

import { describe, expect, it } from "vitest";

import {
  addEntryDraft,
  buildTransportPayload,
  createTransportDraft,
  removeEntryDraft,
  switchTransport,
  transportFromDetail,
  transportHasContent,
  updateEntryDraft,
  type TransportDraft,
} from "./transportState";

/** A draft entry with the given fields (non-existing by default). */
function entry(
  id: string,
  name: string,
  overrides: Partial<TransportDraft["entries"][number]> = {},
): TransportDraft["entries"][number] {
  return {
    id,
    name,
    secret: false,
    value: "",
    existing: false,
    existingSecret: false,
    existingIsSet: false,
    initialValue: "",
    ...overrides,
  };
}

describe("buildTransportPayload — stdio request shapes", () => {
  it("builds an exact stdio create payload with a replace secret entry", () => {
    const draft: TransportDraft = {
      ...createTransportDraft("stdio"),
      command: "npx",
      argsText: "-y\n@acme/server",
      entries: [entry("e1", "API_TOKEN", { secret: true, value: "s3cret" })],
    };
    const result = buildTransportPayload(draft, { nameChanged: false });
    expect(result.ok).toBe(true);
    if (!result.ok) return;
    expect(result.transport).toEqual({
      type: "stdio",
      command: "npx",
      args: ["-y", "@acme/server"],
      env: [{ name: "API_TOKEN", secret: true, action: "replace", value: "s3cret" }],
    });
  });

  it("builds a replace nonsecret entry with its value", () => {
    const draft: TransportDraft = {
      ...createTransportDraft("stdio"),
      command: "npx",
      argsText: "",
      entries: [entry("e1", "DEBUG", { secret: false, value: "1" })],
    };
    const result = buildTransportPayload(draft, { nameChanged: false });
    expect(result.ok).toBe(true);
    if (!result.ok) return;
    expect(result.transport).toEqual({
      type: "stdio",
      command: "npx",
      args: [],
      env: [{ name: "DEBUG", secret: false, action: "replace", value: "1" }],
    });
  });

  it("drops blank argument lines and keeps other lines verbatim", () => {
    const draft: TransportDraft = {
      ...createTransportDraft("stdio"),
      command: "node",
      argsText: "-y\n\n  --flag value\n",
      entries: [],
    };
    const result = buildTransportPayload(draft, { nameChanged: false });
    expect(result.ok).toBe(true);
    if (!result.ok) return;
    if (result.transport.type !== "stdio") throw new Error("expected stdio");
    expect(result.transport.args).toEqual(["-y", "  --flag value"]);
  });
});

describe("buildTransportPayload — retention vs blank replacement", () => {
  const detail = {
    transport: {
      type: "stdio",
      command: "npx",
      args: ["-y"],
      env: [
        { name: "API_TOKEN", secret: true, is_set: true },
        { name: "DEBUG", secret: false, is_set: true, value: "1" },
      ],
    },
  } as const;

  it("sends keep without a value for an untouched set secret", () => {
    const draft = transportFromDetail(detail.transport);
    const result = buildTransportPayload(draft, { nameChanged: false });
    expect(result.ok).toBe(true);
    if (!result.ok) return;
    if (result.transport.type !== "stdio") throw new Error("expected stdio");
    expect(result.transport.env).toEqual([
      { name: "API_TOKEN", secret: true, action: "keep" },
      { name: "DEBUG", secret: false, action: "replace", value: "1" },
    ]);
    expect(result.transport.env[0]).not.toHaveProperty("value");
  });

  it("sends replace with the typed value when the stored secret is replaced", () => {
    const draft = transportFromDetail(detail.transport);
    const result = buildTransportPayload(
      updateEntryDraft(draft, draft.entries[0].id, { value: "rotated" }),
      { nameChanged: false },
    );
    expect(result.ok).toBe(true);
    if (!result.ok) return;
    if (result.transport.type !== "stdio") throw new Error("expected stdio");
    expect(result.transport.env[0]).toEqual({
      name: "API_TOKEN",
      secret: true,
      action: "replace",
      value: "rotated",
    });
  });

  it("re-sends an unchanged nonsecret value as replace with the loaded value", () => {
    const draft = transportFromDetail(detail.transport);
    const result = buildTransportPayload(draft, { nameChanged: false });
    expect(result.ok).toBe(true);
    if (!result.ok) return;
    if (result.transport.type !== "stdio") throw new Error("expected stdio");
    expect(result.transport.env[1]).toEqual({
      name: "DEBUG",
      secret: false,
      action: "replace",
      value: "1",
    });
  });

  it("rejects a keep that is not possible: classification change without a replacement", () => {
    const draft = transportFromDetail(detail.transport);
    const flipped = updateEntryDraft(draft, draft.entries[0].id, { secret: false });
    const result = buildTransportPayload(flipped, { nameChanged: false });
    expect(result.ok).toBe(false);
    if (result.ok) return;
    expect(result.errors.entries[draft.entries[0].id]).toContain("value_required");
    expect(result.errors.keepAfterRename).toBeUndefined();
  });

  it("rejects a blank value for an existing secret that is not set", () => {
    const unsetDetail = {
      transport: {
        type: "stdio",
        command: "npx",
        args: [],
        env: [{ name: "API_TOKEN", secret: true, is_set: false }],
      },
    } as const;
    const draft = transportFromDetail(unsetDetail.transport);
    const result = buildTransportPayload(draft, { nameChanged: false });
    expect(result.ok).toBe(false);
    if (result.ok) return;
    expect(result.errors.entries[draft.entries[0].id]).toContain("value_required");
  });

  it("replaces an unset secret when a value is typed", () => {
    const unsetDetail = {
      transport: {
        type: "stdio",
        command: "npx",
        args: [],
        env: [{ name: "API_TOKEN", secret: true, is_set: false }],
      },
    } as const;
    const draft = transportFromDetail(unsetDetail.transport);
    const filled = updateEntryDraft(draft, draft.entries[0].id, { value: "new" });
    const result = buildTransportPayload(filled, { nameChanged: false });
    expect(result.ok).toBe(true);
    if (!result.ok) return;
    if (result.transport.type !== "stdio") throw new Error("expected stdio");
    expect(result.transport.env[0]).toEqual({
      name: "API_TOKEN",
      secret: true,
      action: "replace",
      value: "new",
    });
  });
});

describe("buildTransportPayload — explicit removal actions", () => {
  const detail = {
    transport: {
      type: "stdio",
      command: "npx",
      args: [],
      env: [
        { name: "API_TOKEN", secret: true, is_set: true },
        { name: "DEBUG", secret: false, is_set: true, value: "1" },
      ],
    },
  } as const;

  it("sends remove without a value for a deleted existing secret entry", () => {
    const draft = transportFromDetail(detail.transport);
    const removed = removeEntryDraft(draft, draft.entries[0].id);
    const result = buildTransportPayload(removed, { nameChanged: false });
    expect(result.ok).toBe(true);
    if (!result.ok) return;
    if (result.transport.type !== "stdio") throw new Error("expected stdio");
    // Derived writes keep authoring order; explicit removals are appended.
    expect(result.transport.env).toEqual([
      { name: "DEBUG", secret: false, action: "replace", value: "1" },
      { name: "API_TOKEN", secret: true, action: "remove" },
    ]);
    expect(result.transport.env[1]).not.toHaveProperty("value");
  });

  it("drops the removal intent when the same name is re-added", () => {
    const draft = transportFromDetail(detail.transport);
    const removed = removeEntryDraft(draft, draft.entries[0].id);
    const readded = addEntryDraft(removed, true);
    const newEntryId = readded.entries[readded.entries.length - 1].id;
    const withValue = updateEntryDraft(readded, newEntryId, {
      name: "API_TOKEN",
      value: "v2",
    });
    const result = buildTransportPayload(withValue, { nameChanged: false });
    expect(result.ok).toBe(true);
    if (!result.ok) return;
    if (result.transport.type !== "stdio") throw new Error("expected stdio");
    expect(result.transport.env).toEqual([
      { name: "DEBUG", secret: false, action: "replace", value: "1" },
      { name: "API_TOKEN", secret: true, action: "replace", value: "v2" },
    ]);
  });
});

describe("buildTransportPayload — entry validation", () => {
  it("rejects duplicate env names", () => {
    const draft: TransportDraft = {
      ...createTransportDraft("stdio"),
      command: "npx",
      argsText: "",
      entries: [
        entry("e1", "API_TOKEN", { secret: true, value: "a" }),
        entry("e2", "API_TOKEN", { secret: true, value: "b" }),
      ],
    };
    const result = buildTransportPayload(draft, { nameChanged: false });
    expect(result.ok).toBe(false);
    if (result.ok) return;
    expect(result.errors.entries["e1"]).toContain("name_duplicate");
    expect(result.errors.entries["e2"]).toContain("name_duplicate");
  });

  it("rejects case-insensitive duplicate header names", () => {
    const draft: TransportDraft = {
      ...createTransportDraft("http"),
      url: "https://example.com/mcp",
      entries: [
        entry("h1", "X-Token", { secret: true, value: "a" }),
        entry("h2", "x-token", { secret: true, value: "b" }),
      ],
    };
    const result = buildTransportPayload(draft, { nameChanged: false });
    expect(result.ok).toBe(false);
    if (result.ok) return;
    expect(result.errors.entries["h1"]).toContain("name_duplicate");
    expect(result.errors.entries["h2"]).toContain("name_duplicate");
  });

  it("rejects env names that are not valid identifiers", () => {
    const draft: TransportDraft = {
      ...createTransportDraft("stdio"),
      command: "npx",
      argsText: "",
      entries: [entry("e1", "1BAD", { value: "a" }), entry("e2", "A-B", { value: "a" })],
    };
    const result = buildTransportPayload(draft, { nameChanged: false });
    expect(result.ok).toBe(false);
    if (result.ok) return;
    expect(result.errors.entries["e1"]).toContain("name_invalid");
    expect(result.errors.entries["e2"]).toContain("name_invalid");
  });

  it("accepts valid header token names and rejects names with separators", () => {
    const draft: TransportDraft = {
      ...createTransportDraft("http"),
      url: "https://example.com/mcp",
      entries: [entry("h1", "X-API-Key", { value: "a" }), entry("h2", "bad name", { value: "a" })],
    };
    const result = buildTransportPayload(draft, { nameChanged: false });
    expect(result.ok).toBe(false);
    if (result.ok) return;
    expect(result.errors.entries["h1"]).toBeUndefined();
    expect(result.errors.entries["h2"]).toContain("name_invalid");
  });

  it("rejects a replace without a value", () => {
    const draft: TransportDraft = {
      ...createTransportDraft("stdio"),
      command: "npx",
      argsText: "",
      entries: [entry("e1", "API_TOKEN", { secret: true, value: "" })],
    };
    const result = buildTransportPayload(draft, { nameChanged: false });
    expect(result.ok).toBe(false);
    if (result.ok) return;
    expect(result.errors.entries["e1"]).toContain("value_required");
  });

  it("rejects a stdio command containing whitespace", () => {
    const draft: TransportDraft = {
      ...createTransportDraft("stdio"),
      command: "npx -y",
      argsText: "",
      entries: [],
    };
    const result = buildTransportPayload(draft, { nameChanged: false });
    expect(result.ok).toBe(false);
    if (result.ok) return;
    expect(result.errors.command).toBe(true);
  });

  it("rejects non-absolute or credential-bearing URLs", () => {
    for (const url of ["ftp://example.com", "http://user:pass@example.com", "not-a-url", ""]) {
      const draft: TransportDraft = {
        ...createTransportDraft("http"),
        url,
        entries: [],
      };
      const result = buildTransportPayload(draft, { nameChanged: false });
      expect(result.ok).toBe(false);
      if (result.ok) return;
      expect(result.errors.url, url).toBe(true);
    }
  });

  it("accepts an absolute http(s) URL without credentials", () => {
    const draft: TransportDraft = {
      ...createTransportDraft("http"),
      url: "https://example.com/mcp",
      entries: [],
    };
    const result = buildTransportPayload(draft, { nameChanged: false });
    expect(result.ok).toBe(true);
    if (!result.ok) return;
    expect(result.transport).toEqual({
      type: "http",
      url: "https://example.com/mcp",
      headers: [],
    });
  });
});

describe("buildTransportPayload — keep after rename", () => {
  const detail = {
    transport: {
      type: "stdio",
      command: "npx",
      args: [],
      env: [{ name: "API_TOKEN", secret: true, is_set: true }],
    },
  } as const;

  it("blocks submission when the server is renamed and a secret would be kept", () => {
    const draft = transportFromDetail(detail.transport);
    const result = buildTransportPayload(draft, { nameChanged: true });
    expect(result.ok).toBe(false);
    if (result.ok) return;
    expect(result.errors.keepAfterRename).toBe(true);
    expect(result.errors.entries[draft.entries[0].id]).toContain("value_required");
  });

  it("allows keeping when the name is unchanged", () => {
    const draft = transportFromDetail(detail.transport);
    const result = buildTransportPayload(draft, { nameChanged: false });
    expect(result.ok).toBe(true);
  });

  it("allows a rename when the kept secret is replaced with a new value", () => {
    const draft = transportFromDetail(detail.transport);
    const replaced = updateEntryDraft(draft, draft.entries[0].id, { value: "new" });
    const result = buildTransportPayload(replaced, { nameChanged: true });
    expect(result.ok).toBe(true);
    if (!result.ok) return;
    if (result.transport.type !== "stdio") throw new Error("expected stdio");
    expect(result.transport.env[0]).toEqual({
      name: "API_TOKEN",
      secret: true,
      action: "replace",
      value: "new",
    });
  });
});

describe("transport drafts", () => {
  it("creates an empty stdio draft by default", () => {
    expect(createTransportDraft()).toEqual({
      type: "stdio",
      command: "",
      argsText: "",
      url: "",
      entries: [],
      removals: [],
    });
  });

  it("hydrates from a detail response without preloading secret values", () => {
    const detail = {
      transport: {
        type: "http",
        url: "https://example.com/mcp",
        headers: [
          { name: "Authorization", secret: true, is_set: true },
          { name: "X-Trace", secret: false, is_set: true, value: "trace-1" },
        ],
      },
    } as const;
    const draft = transportFromDetail(detail.transport);
    expect(draft.type).toBe("http");
    expect(draft.url).toBe("https://example.com/mcp");
    expect(draft.entries).toHaveLength(2);
    expect(draft.entries[0]).toMatchObject({
      name: "Authorization",
      secret: true,
      value: "",
      existing: true,
      existingSecret: true,
      existingIsSet: true,
    });
    expect(draft.entries[1]).toMatchObject({
      name: "X-Trace",
      secret: false,
      value: "trace-1",
      initialValue: "trace-1",
      existing: true,
      existingSecret: false,
    });
  });

  it("hydrates stdio args one per line", () => {
    const detail = {
      transport: {
        type: "stdio",
        command: "node",
        args: ["-y", "server.js"],
        env: [],
      },
    } as const;
    const draft = transportFromDetail(detail.transport);
    expect(draft.command).toBe("node");
    expect(draft.argsText).toBe("-y\nserver.js");
    expect(draft.entries).toEqual([]);
  });

  it("resets every field and entry when the transport type switches", () => {
    const draft: TransportDraft = {
      ...createTransportDraft("stdio"),
      command: "npx",
      argsText: "-y",
      entries: [entry("e1", "API_TOKEN", { secret: true, value: "v" })],
      removals: [{ id: "r1", name: "OLD", secret: true }],
    };
    expect(switchTransport(draft, "http")).toEqual({
      type: "http",
      command: "",
      argsText: "",
      url: "",
      entries: [],
      removals: [],
    });
  });

  it("reports content for the switch confirmation", () => {
    expect(transportHasContent(createTransportDraft("stdio"))).toBe(false);
    expect(transportHasContent({ ...createTransportDraft("stdio"), command: " npx " })).toBe(true);
    expect(transportHasContent({ ...createTransportDraft("http"), url: "https://x.dev" })).toBe(true);
    expect(
      transportHasContent({ ...createTransportDraft("stdio"), entries: [entry("e1", "A")] }),
    ).toBe(true);
  });

  it("moves an existing entry to removals and drops a new one outright", () => {
    const detail = {
      transport: {
        type: "stdio",
        command: "npx",
        args: [],
        env: [{ name: "API_TOKEN", secret: true, is_set: true }],
      },
    } as const;
    const draft = transportFromDetail(detail.transport);
    const withNew = addEntryDraft(draft, false);
    expect(withNew.entries).toHaveLength(2);

    const removedExisting = removeEntryDraft(withNew, draft.entries[0].id);
    expect(removedExisting.entries.map((item) => item.id)).not.toContain(draft.entries[0].id);
    expect(removedExisting.removals).toEqual([
      { id: draft.entries[0].id, name: "API_TOKEN", secret: true },
    ]);

    const removedNew = removeEntryDraft(removedExisting, withNew.entries[1].id);
    expect(removedNew.removals).toEqual([
      { id: draft.entries[0].id, name: "API_TOKEN", secret: true },
    ]);
  });
});

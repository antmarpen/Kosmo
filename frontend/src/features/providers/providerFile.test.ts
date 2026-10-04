import { describe, expect, it, vi } from "vitest";

import { MAX_PROVIDER_FILE_BYTES, isSupportedConfigFile, parseAuthArray, parseConfigObject, readProviderFile } from "./providerFile";

describe("config file support", () => {
  it.each(["opencode.json", "CONFIG.JSON", "auth.jsonc", "config.JSONC"])("accepts %s", (filename) => {
    expect(isSupportedConfigFile(filename)).toBe(true);
  });

  it.each(["payload.js", "bundle.mjs", "script.cjs", "noextension", "archive.json.gz", "tricky.json.js"])("rejects %s", (filename) => {
    expect(isSupportedConfigFile(filename)).toBe(false);
  });
});

describe("parseConfigObject", () => {
  it("parses strict JSON objects", () => {
    expect(parseConfigObject('{"providers":{"openai":{"options":{}}}}')).toEqual({ providers: { openai: { options: {} } } });
  });

  it("parses JSONC with line comments, block comments, and trailing commas", () => {
    const text = `{
      // primary provider
      "providers": {
        "openai": { "options": {}, "models": { "gpt-4.1": {} } }, /* trailing comma below */
      },
    }`;
    expect(parseConfigObject(text)).toEqual({ providers: { openai: { options: {}, models: { "gpt-4.1": {} } } } });
  });

  it("rejects legacy provider object documents", () => {
    expect(parseConfigObject('{"provider":{"openai":{}}}')).toBeNull();
  });

  it.each([
    ["array root", "[1, 2]"],
    ["string root", '"provider"'],
    ["number root", "42"],
    ["empty input", ""],
    ["malformed input", "{ provider: }"],
  ])("rejects %s", (_name, text) => {
    expect(parseConfigObject(text)).toBeNull();
  });
});

describe("parseAuthArray", () => {
  it("accepts v2 API-key credentials", () => {
    expect(parseAuthArray('[{"id":"cred_1","integrationID":"openai","label":"API key","active":true,"value":{"type":"key","key":"secret"}}]'))
      .toEqual([{ id: "cred_1", integrationID: "openai", label: "API key", active: true, value: { type: "key", key: "secret" } }]);
  });

  it.each([
    ["object root", '{"openai":{"type":"api","key":"secret"}}'],
    ["OAuth credential", '[{"id":"x","integrationID":"openai","label":"OAuth","active":true,"value":{"type":"oauth"}}]'],
    ["malformed entry", '[{"value":{"type":"api","key":"secret"}}]'],
  ])("rejects %s", (_name, text) => {
    expect(parseAuthArray(text)).toBeNull();
  });
});

describe("readProviderFile", () => {
  it("reads a .jsonc file into a parsed object", async () => {
    const result = await readProviderFile(new File(['{ // comment\n"providers": {} }'], "opencode.jsonc"));
    expect(result).toEqual({ ok: true, filename: "opencode.jsonc", text: '{ // comment\n"providers": {} }', value: { providers: {} } });
  });

  it("rejects unsupported extensions without reading the file", async () => {
    const file = new File(["{}"], "payload.js");
    const readSpy = vi.spyOn(file, "text");
    const result = await readProviderFile(file);
    expect(result).toEqual({ ok: false, failure: { reason: "unsupported_type", filename: "payload.js" } });
    expect(readSpy).not.toHaveBeenCalled();
  });

  it("rejects files above the size limit without reading them", async () => {
    const file = new File(["x".repeat(MAX_PROVIDER_FILE_BYTES + 1)], "opencode.json");
    const readSpy = vi.spyOn(file, "text");
    const result = await readProviderFile(file);
    expect(result).toEqual({ ok: false, failure: { reason: "too_large", filename: "opencode.json" } });
    expect(readSpy).not.toHaveBeenCalled();
  });

  it("reports read failures instead of throwing", async () => {
    const file = new File(["{}"], "opencode.json");
    vi.spyOn(file, "text").mockRejectedValue(new Error("disk error"));
    const result = await readProviderFile(file);
    expect(result).toEqual({ ok: false, failure: { reason: "read_failed", filename: "opencode.json" } });
  });

  it("reports invalid JSON content", async () => {
    const result = await readProviderFile(new File(["not json"], "opencode.json"));
    expect(result).toEqual({ ok: false, failure: { reason: "invalid_json", filename: "opencode.json" } });
  });
});

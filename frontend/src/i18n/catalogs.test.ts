import { describe, expect, it } from "vitest";

import en from "./locales/en.json";
import es from "./locales/es.json";

/** Collects dotted key paths for every leaf value in a nested catalog. */
function collectLeafKeys(value: unknown, prefix = ""): string[] {
  if (typeof value === "string") return [prefix];
  if (value === null || typeof value !== "object") {
    throw new TypeError(`Catalog leaf at "${prefix}" must be a string`);
  }
  return Object.entries(value).flatMap(([key, child]) =>
    collectLeafKeys(child, prefix ? `${prefix}.${key}` : key),
  );
}

describe("translation catalogs", () => {
  it("en and es expose exactly the same key structure", () => {
    expect(collectLeafKeys(es).sort()).toEqual(collectLeafKeys(en).sort());
  });

  it("only contains non-empty string leaf values in both languages", () => {
    for (const [locale, catalog] of [
      ["en", en],
      ["es", es],
    ] as const) {
      for (const key of collectLeafKeys(catalog)) {
        const value = key
          .split(".")
          .reduce<unknown>(
            (acc, part) => (acc as Record<string, unknown>)[part],
            catalog,
          );
        expect(value, `${locale}:${key}`).toEqual(expect.any(String));
        expect(String(value).trim().length, `${locale}:${key}`).toBeGreaterThan(0);
      }
    }
  });

  it("exposes the common and auth namespaces required by WP-02", () => {
    for (const catalog of [en, es]) {
      expect(Object.keys(catalog)).toEqual(expect.arrayContaining(["common", "auth"]));
      expect(catalog.common?.cancel).toEqual(expect.any(String));
      expect(catalog.common?.submit).toEqual(expect.any(String));
      expect(catalog.auth?.login?.title).toEqual(expect.any(String));
      expect(catalog.auth?.login?.username).toEqual(expect.any(String));
      expect(catalog.auth?.login?.password).toEqual(expect.any(String));
      expect(catalog.auth?.login?.action).toEqual(expect.any(String));
    }
  });
});

import "@testing-library/jest-dom/vitest";

import { cleanup } from "@testing-library/react";
import i18next from "i18next";
import { afterEach } from "vitest";

// jsdom does not implement the object URL APIs; provide deterministic stubs so
// artifact-download flows behave the same across environments and Node versions.
if (typeof URL.createObjectURL !== "function") {
  URL.createObjectURL = () => "blob:mock";
}
if (typeof URL.revokeObjectURL !== "function") {
  URL.revokeObjectURL = () => {};
}

// The i18n module initializes i18next on import (guarded, idempotent).
import "@/i18n";

afterEach(async () => {
  cleanup();
  // Reset language and storage so tests are order-independent.
  await i18next.changeLanguage("en");
  window.localStorage.clear();
});

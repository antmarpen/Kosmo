import "@testing-library/jest-dom/vitest";

import { cleanup } from "@testing-library/react";
import i18next from "i18next";
import { afterEach } from "vitest";

// The i18n module initializes i18next on import (guarded, idempotent).
import "@/i18n";

afterEach(async () => {
  cleanup();
  // Reset language and storage so tests are order-independent.
  await i18next.changeLanguage("en");
  window.localStorage.clear();
});

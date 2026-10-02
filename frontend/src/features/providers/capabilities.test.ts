import { describe, expect, it } from "vitest";
import { getProviderCapability, providerCapabilities, canProceedWithProvider } from "./capabilities";

describe("provider capabilities", () => {
  it("describes all supported provider types with localized label and description keys", () => {
    expect(providerCapabilities.map(({ type }) => type)).toEqual(["opencode", "claude_code", "codex"]);
    for (const capability of providerCapabilities) {
      expect(capability.label).toEqual(expect.any(String));
      expect(capability.description).toEqual(expect.any(String));
      expect(capability.authMethods.length).toBeGreaterThan(0);
    }
  });

  it("allows OpenCode with config-file authentication only", () => {
    expect(getProviderCapability("opencode")).toMatchObject({ available: true, authMethods: ["config"] });
    expect(canProceedWithProvider("opencode")).toBe(true);
  });

  it.each(["claude_code", "codex"] as const)("keeps %s unavailable while advertising its planned auth methods", (type) => {
    expect(getProviderCapability(type)).toMatchObject({ available: false, authMethods: ["api_key", "config"] });
    expect(canProceedWithProvider(type)).toBe(false);
  });
});

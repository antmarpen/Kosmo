import { renderHook, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { api, clearTokens, setTokens } from "@/api/auth";
import { useCurrentUser } from "./useCurrentUser";

describe("useCurrentUser", () => {
  afterEach(() => { vi.restoreAllMocks(); clearTokens(); });

  it("loads the current user and capabilities through the authenticated API in parallel", async () => {
    setTokens("access", "refresh");
    const getSpy = vi.spyOn(api, "GET").mockImplementation((path: string) => Promise.resolve({
      data: path === "/auth/me"
        ? { id: "u1", username: "alex", role: "builder" }
        : { scopes: { personal: true, groups: ["g1"], global: false }, groups: [{ id: "g1", name: "Team", role: "manager" }] },
      error: undefined, response: new Response(),
    }) as never);

    const { result } = renderHook(() => useCurrentUser());
    await waitFor(() => expect(result.current.loading).toBe(false));
    expect(getSpy).toHaveBeenCalledTimes(2);
    expect(getSpy).toHaveBeenCalledWith("/auth/me");
    expect(getSpy).toHaveBeenCalledWith("/auth/capabilities");
    expect(result.current.user).toEqual({ id: "u1", username: "alex", role: "builder" });
    expect(result.current.capabilities).toEqual({ scopes: { personal: true, groups: ["g1"], global: false }, groups: [{ id: "g1", name: "Team", role: "manager" }] });
    expect(result.current.error).toBeNull();
  });
});

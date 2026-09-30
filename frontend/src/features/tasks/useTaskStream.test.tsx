import { act, renderHook } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { setTokens } from "@/api/auth";
import { useTaskStream } from "./useTaskStream";

describe("useTaskStream polling fallback", () => {
  afterEach(() => { vi.useRealTimers(); vi.restoreAllMocks(); });

  it("restarts polling after a successful stream clears the prior timer", async () => {
    vi.useFakeTimers();
    setTokens("access", "refresh");
    let attempt = 0;
    vi.spyOn(globalThis, "fetch").mockImplementation(async () => {
      attempt++;
      if (attempt === 4) return new Response(new ReadableStream({ start(controller) { controller.close(); } }), { status: 200 });
      return new Response(null, { status: 503 });
    });
    const poll = vi.fn();
    const { unmount } = renderHook(() => useTaskStream(undefined, vi.fn(), poll));
    await act(async () => { await vi.advanceTimersByTimeAsync(60_000); });
    expect(attempt).toBeGreaterThanOrEqual(7);
    expect(poll).toHaveBeenCalled();
    unmount();
  });
});

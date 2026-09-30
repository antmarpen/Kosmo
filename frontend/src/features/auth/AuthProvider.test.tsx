import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router";
import { StrictMode } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { AuthProvider, RequireAuth, useAuth } from "./AuthProvider";
import { LoginPage, resolveAuthenticatedDestination } from "./LoginPage";
import { api, clearTokens, setTokens, setLogoutHandler } from "@/api/auth";

describe("authentication flow", () => {
  afterEach(() => { vi.restoreAllMocks(); clearTokens(); setLogoutHandler(() => undefined); });

  it("defaults to the app landing instead of returning to a public auth route", () => {
    expect(resolveAuthenticatedDestination({ pathname: "/login" })).toBe("/tasks/new");
  });

  it("logs in, persists refresh token and permits guarded route", async () => {
    const fetchMock = vi.spyOn(globalThis, "fetch").mockResolvedValue(new Response(JSON.stringify({ access_token: "access", refresh_token: "refresh", token_type: "bearer", expires_in: 900 }), { status: 200, headers: { "Content-Type": "application/json" } }));
    render(<AuthProvider><MemoryRouter initialEntries={["/login"]}><Routes><Route path="/login" element={<LoginPage />} /><Route path="/private" element={<RequireAuth><h1>Private</h1></RequireAuth>} /></Routes></MemoryRouter></AuthProvider>);
    fireEvent.change(screen.getByLabelText("Username"), { target: { value: "admin" } });
    fireEvent.change(screen.getByLabelText("Password"), { target: { value: "secret" } });
    fireEvent.submit(screen.getByRole("form", { name: "Sign in" }));
    await waitFor(() => expect(fetchMock).toHaveBeenCalled());
    expect(fetchMock.mock.calls[0][0]).toBeInstanceOf(Request);
    await waitFor(() => expect(localStorage.getItem("kosmo.refresh")).toBe("refresh"));
  });

  it("redirects unauthenticated users to login", async () => {
    render(<AuthProvider><MemoryRouter initialEntries={["/private"]}><Routes><Route path="/private" element={<RequireAuth><h1>Private</h1></RequireAuth>} /><Route path="/login" element={<h1>Login</h1>} /></Routes></MemoryRouter></AuthProvider>);
    expect(await screen.findByRole("heading", { name: "Login" })).toBeInTheDocument();
  });

  it("keeps a deep link guarded while session restoration is pending", async () => {
    localStorage.setItem("kosmo.refresh", "persisted-refresh");
    let finishRefresh!: (response: Response) => void;
    const fetchMock = vi.spyOn(globalThis, "fetch").mockImplementation(() => new Promise((resolve) => { finishRefresh = resolve; }));
    render(<StrictMode><AuthProvider><MemoryRouter initialEntries={["/tasks/abc?tab=recent#item"]}><Routes>
      <Route path="/tasks/:id" element={<RequireAuth><h1>Private</h1></RequireAuth>} />
      <Route path="/login" element={<h1>Login</h1>} />
    </Routes></MemoryRouter></AuthProvider></StrictMode>);
    expect(screen.getByRole("status")).toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: "Login" })).not.toBeInTheDocument();
    finishRefresh(new Response(JSON.stringify({ access_token: "restored", refresh_token: "rotated" }), { status: 200, headers: { "Content-Type": "application/json" } }));
    expect(await screen.findByRole("heading", { name: "Private" })).toBeInTheDocument();
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });

  it("returns to the original deep link after login", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue(new Response(JSON.stringify({ access_token: "access", refresh_token: "refresh" }), { status: 200, headers: { "Content-Type": "application/json" } }));
    render(<AuthProvider><MemoryRouter initialEntries={["/tasks/abc?tab=recent#item"]}><Routes>
      <Route path="/tasks/:id" element={<RequireAuth><h1>Private</h1></RequireAuth>} />
      <Route path="/login" element={<LoginPage />} />
    </Routes></MemoryRouter></AuthProvider>);
    fireEvent.change(await screen.findByLabelText("Username"), { target: { value: "admin" } });
    fireEvent.change(screen.getByLabelText("Password"), { target: { value: "secret" } });
    fireEvent.submit(screen.getByRole("form", { name: "Sign in" }));
    expect(await screen.findByRole("heading", { name: "Private" })).toBeInTheDocument();
  });

  it("defaults to the app landing when the remembered destination is the login route", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue(new Response(JSON.stringify({ access_token: "access", refresh_token: "refresh" }), { status: 200, headers: { "Content-Type": "application/json" } }));
    render(<AuthProvider><MemoryRouter initialEntries={[{ pathname: "/login", state: { from: { pathname: "/login" } } }]}><Routes>
      <Route path="/login" element={<LoginPage />} />
      <Route path="/tasks/new" element={<h1>New task</h1>} />
    </Routes></MemoryRouter></AuthProvider>);
    fireEvent.change(screen.getByLabelText("Username"), { target: { value: "admin" } });
    fireEvent.change(screen.getByLabelText("Password"), { target: { value: "secret" } });
    fireEvent.submit(screen.getByRole("form", { name: "Sign in" }));
    expect(await screen.findByRole("heading", { name: "New task" })).toBeInTheDocument();
  });

  it("refreshes once after an expired access token and retries the original call", async () => {
    localStorage.setItem("kosmo.refresh", "expired-refresh");
    const fetchMock = vi.spyOn(globalThis, "fetch")
      .mockResolvedValueOnce(new Response(null, { status: 401 }))
      .mockResolvedValueOnce(new Response(JSON.stringify({ access_token: "fresh", refresh_token: "rotated" }), { status: 200, headers: { "Content-Type": "application/json" } }))
      .mockResolvedValueOnce(new Response(JSON.stringify({ username: "admin", role: "admin" }), { status: 200, headers: { "Content-Type": "application/json" } }));
    setTokens("expired", "expired-refresh");
    await api.GET("/auth/me");
    expect(fetchMock).toHaveBeenCalledTimes(3);
    expect(String(fetchMock.mock.calls[1][0])).toContain("/auth/refresh");
    expect((fetchMock.mock.calls[2][0] as Request).url).toContain("/auth/me");
    expect(localStorage.getItem("kosmo.refresh")).toBe("rotated");
  });

  it("does not rotate refresh again for a late 401 from the prior access token", async () => {
    setTokens("expired", "one-use-refresh");
    const pendingInitial: Array<(response: Response) => void> = [];
    let refreshCalls = 0;
    vi.spyOn(globalThis, "fetch").mockImplementation((input, init) => {
      const url = input instanceof Request ? input.url : String(input);
      const headers = input instanceof Request ? input.headers : new Headers(init?.headers);
      if (url.endsWith("/auth/me")) {
        if (headers.get("Authorization") === "Bearer fresh") return Promise.resolve(new Response(JSON.stringify({ username: "admin", role: "admin" }), { status: 200, headers: { "Content-Type": "application/json" } }));
        return new Promise((resolve) => pendingInitial.push(resolve));
      }
      if (url.endsWith("/auth/refresh")) {
        refreshCalls++;
        return Promise.resolve(new Response(JSON.stringify({ access_token: "fresh", refresh_token: "rotated" }), { status: 200, headers: { "Content-Type": "application/json" } }));
      }
      throw new Error(`Unexpected request: ${url}`);
    });
    const first = api.GET("/auth/me");
    const second = api.GET("/auth/me");
    await waitFor(() => expect(pendingInitial).toHaveLength(2));
    pendingInitial[0](new Response(null, { status: 401 }));
    await waitFor(() => expect(localStorage.getItem("kosmo.refresh")).toBe("rotated"));
    pendingInitial[1](new Response(null, { status: 401 }));
    await Promise.all([first, second]);
    expect(refreshCalls).toBe(1);
  });

  it("posts logout and clears stored credentials", async () => {
    setTokens("access", "refresh-to-revoke");
    const fetchMock = vi.spyOn(globalThis, "fetch").mockResolvedValue(new Response(null, { status: 204 }));
    function LogoutButton() { const auth = useAuth(); return <button onClick={() => void auth.logout()}>Logout</button>; }
    render(<AuthProvider><MemoryRouter><LogoutButton /></MemoryRouter></AuthProvider>);
    fireEvent.click(screen.getByRole("button", { name: "Logout" }));
    await waitFor(() => expect(localStorage.getItem("kosmo.refresh")).toBeNull());
    expect((fetchMock.mock.calls[0][0] as Request).url).toContain("/auth/logout");
    expect((fetchMock.mock.calls[0][0] as Request).method).toBe("POST");
  });

  it("clears auth state and invokes logout handling when refresh fails", async () => {
    setTokens("expired", "revoked-refresh");
    const onLogout = vi.fn();
    setLogoutHandler(onLogout);
    vi.spyOn(globalThis, "fetch")
      .mockResolvedValueOnce(new Response(null, { status: 401 }))
      .mockResolvedValueOnce(new Response(null, { status: 401 }));
    await api.GET("/auth/me");
    expect(localStorage.getItem("kosmo.refresh")).toBeNull();
    expect(onLogout).toHaveBeenCalledOnce();
  });
});

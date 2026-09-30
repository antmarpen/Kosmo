import createClient from "openapi-fetch";
import type { paths } from "./schema";

const client = createClient<paths>({ baseUrl: `${globalThis.location?.origin ?? "http://localhost"}/api`, fetch: (...args) => globalThis.fetch(...args) });
const REFRESH_KEY = "kosmo.refresh";
let accessToken: string | null = null;
let refreshInFlight: Promise<boolean> | null = null;
let logoutHandler: (() => void) | null = null;

export function setTokens(access: string, refresh: string) {
  accessToken = access;
  localStorage.setItem(REFRESH_KEY, refresh);
}
export function clearTokens() {
  accessToken = null;
  localStorage.removeItem(REFRESH_KEY);
}
export function hasAccessToken() { return accessToken !== null; }
export function getAccessToken() { return accessToken; }
export async function restoreSession() { if (!localStorage.getItem(REFRESH_KEY)) return false; const ok = await renewSession(); if (!ok) clearTokens(); return ok; }
export function setLogoutHandler(handler: () => void) { logoutHandler = handler; }

async function refresh(): Promise<boolean> {
  const refreshToken = localStorage.getItem(REFRESH_KEY);
  if (!refreshToken) return false;
  try {
    const response = await fetch("/api/auth/refresh", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ refresh_token: refreshToken }),
    });
    if (!response.ok) return false;
    const data = await response.json();
    setTokens(data.access_token, data.refresh_token);
    return true;
  } catch { return false; }
}

function renewSession(): Promise<boolean> {
  refreshInFlight ??= refresh().finally(() => { refreshInFlight = null; });
  return refreshInFlight;
}

/** Authenticated transport for streaming endpoints that cannot use openapi-fetch's JSON parser. */
export async function authenticatedFetch(input: RequestInfo | URL, init?: RequestInit): Promise<Response> {
  const resolvedInput = typeof input === "string" ? new URL(input, globalThis.location?.href ?? "http://localhost") : input;
  const request = new Request(resolvedInput, init);
  if (accessToken) request.headers.set("Authorization", `Bearer ${accessToken}`);
  let response = await fetch(request);
  if (response.status !== 401 || request.url.endsWith("/auth/login") || request.url.endsWith("/auth/refresh")) return response;
  if (await renewSession()) {
    const headers = new Headers(request.headers);
    headers.set("Authorization", `Bearer ${accessToken}`);
    response = await fetch(new Request(request, { headers }));
    return response;
  }
  clearTokens();
  logoutHandler?.();
  if (typeof window !== "undefined") window.location.assign("/login");
  return response;
}

client.use({
  onRequest({ request }) {
    if (accessToken) request.headers.set("Authorization", `Bearer ${accessToken}`);
    return request;
  },
  async onResponse({ request, response }) {
    if (response.status !== 401 || request.url.endsWith("/auth/login") || request.url.endsWith("/auth/refresh")) return response;
    const currentAuthorization = accessToken ? `Bearer ${accessToken}` : null;
    if (currentAuthorization && request.headers.get("Authorization") !== currentAuthorization) {
      const headers = new Headers(request.headers);
      headers.set("Authorization", currentAuthorization);
      return fetch(new Request(request, { headers }));
    }
    if (await renewSession()) {
      const headers = new Headers(request.headers);
      headers.set("Authorization", `Bearer ${accessToken}`);
      return fetch(new Request(request, { headers }));
    }
    clearTokens();
    logoutHandler?.();
    if (typeof window !== "undefined") window.location.assign("/login");
    return response;
  },
});

export const api = client;
export async function loginRequest(username: string, password: string) {
  return api.POST("/auth/login", { body: { username, password } });
}
export async function logoutRequest() {
  const token = localStorage.getItem(REFRESH_KEY);
  if (!token) return;
  await api.POST("/auth/logout", { body: { refresh_token: token } } as never);
}

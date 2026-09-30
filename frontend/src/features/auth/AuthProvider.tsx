import { createContext, useContext, useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { Navigate, useLocation } from "react-router";
import { clearTokens, hasAccessToken, loginRequest, logoutRequest, restoreSession, setLogoutHandler, setTokens } from "@/api/auth";

type AuthValue = { authenticated: boolean; restoring: boolean; login: (username: string, password: string) => Promise<void>; logout: () => Promise<void> };
const AuthContext = createContext<AuthValue | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [authenticated, setAuthenticated] = useState(hasAccessToken);
  const [restoring, setRestoring] = useState(() => !hasAccessToken());
  const restorationStarted = useRef(false);
  useEffect(() => {
    if (!restoring || restorationStarted.current) return;
    restorationStarted.current = true;
    void restoreSession()
      .then(setAuthenticated)
      .catch(() => { clearTokens(); setAuthenticated(false); })
      .finally(() => setRestoring(false));
  }, [restoring]);
  const value = useMemo<AuthValue>(() => ({
    authenticated,
    restoring,
    async login(username, password) {
      const { data, error } = await loginRequest(username, password);
      if (error || !data) throw new Error("Invalid credentials");
      const tokens = data as { access_token: string; refresh_token: string };
      setTokens(tokens.access_token, tokens.refresh_token);
      setAuthenticated(true);
    },
    async logout() {
      try { await logoutRequest(); } finally { clearTokens(); setAuthenticated(false); }
    },
  }), [authenticated, restoring]);
  setLogoutHandler(() => setAuthenticated(false));
  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}
export function useAuth() {
  const value = useContext(AuthContext);
  if (!value) throw new Error("useAuth must be used within AuthProvider");
  return value;
}
export function RequireAuth({ children }: { children: ReactNode }) {
  const { authenticated, restoring } = useAuth();
  const location = useLocation();
  if (restoring) return <div role="status" aria-live="polite">Loading…</div>;
  return authenticated ? children : <Navigate to="/login" replace state={{ from: location }} />;
}

import { useEffect, useState } from "react";
import { api } from "@/api/auth";
import type { components } from "@/api/schema";

export type CurrentUser = components["schemas"]["UserResponse"];
export type UserCapabilities = {
  scopes: { personal: boolean; groups: string[]; global: boolean };
  groups: Array<{ id: string; name: string; role: string }>;
};

export function useCurrentUser() {
  const [user, setUser] = useState<CurrentUser | null>(null);
  const [capabilities, setCapabilities] = useState<UserCapabilities | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<Error | null>(null);

  useEffect(() => {
    let active = true;
    Promise.all([api.GET("/auth/me"), api.GET("/auth/capabilities")])
      .then(([userResponse, capabilityResponse]) => {
        const userResult = userResponse as { data: CurrentUser; error?: unknown };
        const capabilityResult = capabilityResponse as { data: UserCapabilities; error?: unknown };
        if (userResult.error) throw userResult.error;
        if (capabilityResult.error) throw capabilityResult.error;
        if (active) {
          setUser(userResult.data);
          setCapabilities(capabilityResult.data);
        }
      })
      .catch((cause: unknown) => {
        if (active) setError(cause instanceof Error ? cause : new Error("Unable to load current user"));
      })
      .finally(() => { if (active) setLoading(false); });
    return () => { active = false; };
  }, []);

  return { user, capabilities, loading, error };
}

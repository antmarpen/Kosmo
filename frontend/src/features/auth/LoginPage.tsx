import { useTranslation } from "react-i18next";

import { AppLogo } from "@/components/app-logo";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Icon } from "@/components/ui/icon";
import { Input } from "@/components/ui/input";

import { LanguageSwitcher } from "./LanguageSwitcher";
import { useAuth } from "./AuthProvider";
import { useEffect, useState, type FormEvent } from "react";
import { useLocation, useNavigate } from "react-router";

type IntendedLocation = { pathname?: string; search?: string; hash?: string };

/** Only return to known application areas; auth and other public paths fall back. */
export function resolveAuthenticatedDestination(from?: IntendedLocation | null): string {
  const pathname = from?.pathname;
  if (!pathname || !pathname.startsWith("/") || pathname.startsWith("//") || pathname.includes("\\")) return "/tasks/new";
  const appRoots = ["/tasks", "/workflows", "/context", "/admin"];
  const isAppRoute = pathname === "/" || appRoots.some((root) => pathname === root || pathname.startsWith(`${root}/`));
  return isAppRoute ? `${pathname}${from.search ?? ""}${from.hash ?? ""}` : "/tasks/new";
}

/**
 * Login page (WP-02, auth wiring added in WP-06). Submission goes through
 * `AuthProvider.login`; in-flight feedback is delegated to the shared
 * `Button` `loading` prop (spinner, aria-busy, disabled). Layout is
 * mobile-first: full-height column, fluid card up to max-w-sm.
 */
export function LoginPage() {
  const { t } = useTranslation();
  const { login, authenticated } = useAuth();
  const navigate = useNavigate();
  const location = useLocation();
  const from = (location.state as { from?: { pathname?: string; search?: string; hash?: string } } | null)?.from;
  const destination = resolveAuthenticatedDestination(from);
  const [error, setError] = useState(false);
  const [pending, setPending] = useState(false);
  useEffect(() => { if (authenticated) navigate(destination, { replace: true }); }, [authenticated, destination, navigate]);
  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault(); setError(false); setPending(true);
    const values = new FormData(event.currentTarget);
    try { await login(String(values.get("username")), String(values.get("password"))); navigate(destination, { replace: true }); }
    catch { setError(true); }
    finally { setPending(false); }
  }

  return (
    <div className="flex min-h-dvh flex-col bg-background text-foreground">
      <header className="flex justify-end px-4 py-3 sm:px-6">
        <LanguageSwitcher />
      </header>

      <main className="flex flex-1 items-center justify-center px-4 pb-16 sm:px-6">
        <div className="flex w-full max-w-sm flex-col items-center">
          <AppLogo className="mb-6" />

          <Card className="w-full">
            <CardHeader>
              <CardTitle asChild>
                <h1 className="text-xl leading-tight font-semibold tracking-tight text-balance">
                  {t("auth.login.title")}
                </h1>
              </CardTitle>
              <CardDescription>{t("auth.login.subtitle")}</CardDescription>
            </CardHeader>
            <CardContent>
              <form
                className="grid gap-4"
                aria-label={t("auth.login.title")}
                onSubmit={submit}
              >
                <div className="grid gap-2">
                  <label
                    htmlFor="login-username"
                    className="text-sm leading-none font-medium"
                  >
                    {t("auth.login.username")}
                  </label>
                  <Input
                    id="login-username"
                    name="username"
                    autoComplete="username"
                    placeholder={t("auth.login.usernamePlaceholder")}
                    required
                  />
                </div>
                <div className="grid gap-2">
                  <label
                    htmlFor="login-password"
                    className="text-sm leading-none font-medium"
                  >
                    {t("auth.login.password")}
                  </label>
                  <Input
                    id="login-password"
                    name="password"
                    type="password"
                    autoComplete="current-password"
                    placeholder={t("auth.login.passwordPlaceholder")}
                    required
                  />
                </div>
                {error && <p role="alert" className="text-sm text-destructive">{t("auth.login.error")}</p>}
                <Button type="submit" className="w-full" loading={pending}>
                  <Icon name="login" aria-hidden="true" />
                  {t("auth.login.action")}
                </Button>
              </form>
            </CardContent>
          </Card>
        </div>
      </main>
    </div>
  );
}

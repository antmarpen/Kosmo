import { useTranslation } from "react-i18next";
import { useLocation } from "react-router";

export function PlaceholderPage() {
  const { t } = useTranslation();
  const location = useLocation();
  const titles: Record<string, "nav.routeTitles.tasks.history" | "nav.routeTitles.workflows" | "nav.routeTitles.applications" | "nav.routeTitles.context" | "nav.routeTitles.admin.agents" | "nav.routeTitles.admin.mcps" | "nav.routeTitles.admin.extensions" | "nav.routeTitles.admin.repositories" | "nav.routeTitles.admin.applications" | "nav.routeTitles.admin.audit"> = {
    "/tasks/history": "nav.routeTitles.tasks.history", "/workflows": "nav.routeTitles.workflows", "/applications": "nav.routeTitles.applications", "/context": "nav.routeTitles.context",
    "/admin/agents": "nav.routeTitles.admin.agents", "/admin/mcps": "nav.routeTitles.admin.mcps",
    "/admin/extensions": "nav.routeTitles.admin.extensions", "/admin/repositories": "nav.routeTitles.admin.repositories", "/admin/applications": "nav.routeTitles.admin.applications", "/admin/audit": "nav.routeTitles.admin.audit",
  };
  return <section className="mx-auto flex w-full max-w-7xl flex-1 flex-col px-5 py-9 sm:px-8 sm:py-12">
    <h1 className="text-2xl font-semibold tracking-tight text-balance">{t(titles[location.pathname] ?? "nav.comingSoon")}</h1>
    <p className="mt-2 max-w-2xl text-sm leading-6 text-muted-foreground">{t("nav.comingSoon")}</p>
  </section>;
}

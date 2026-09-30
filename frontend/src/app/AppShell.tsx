import { useEffect, useRef, useState } from "react";
import { NavLink, Outlet, useLocation } from "react-router";
import { useTranslation } from "react-i18next";

import { AppLogo } from "@/components/app-logo";
import { LanguageSwitcher } from "@/features/auth/LanguageSwitcher";
import { cn } from "@/lib/utils";
import { useAuth } from "@/features/auth/AuthProvider";

type NavLabelKey = "nav.tasks" | "nav.newTask" | "nav.history" | "nav.workflows" | "nav.context" | "nav.administration" | "nav.agents" | "nav.mcps" | "nav.skills" | "nav.extensions" | "nav.repositories" | "nav.applications" | "nav.audit";
type NavItem = { id: string; label_message_key: NavLabelKey; icon: string; route?: string; children?: NavItem[] };
export const navigation: NavItem[] = [
  { id: "tasks", label_message_key: "nav.tasks", icon: "▤", children: [
    { id: "new-task", label_message_key: "nav.newTask", icon: "+", route: "/tasks/new" },
    { id: "history", label_message_key: "nav.history", icon: "◷", route: "/tasks/history" },
  ] },
  { id: "workflows", label_message_key: "nav.workflows", icon: "⌘", route: "/workflows" },
  { id: "context", label_message_key: "nav.context", icon: "◇", route: "/context" },
  { id: "administration", label_message_key: "nav.administration", icon: "⚙", children: [
    { id: "agents", label_message_key: "nav.agents", icon: "◉", route: "/admin/agents" },
    { id: "mcps", label_message_key: "nav.mcps", icon: "⇄", route: "/admin/mcps" },
    { id: "skills", label_message_key: "nav.skills", icon: "✳", route: "/admin/skills" },
    { id: "extensions", label_message_key: "nav.extensions", icon: "⊞", route: "/admin/extensions" },
    { id: "repositories", label_message_key: "nav.repositories", icon: "⌂", route: "/admin/repositories" },
    { id: "applications", label_message_key: "nav.applications", icon: "▦", route: "/admin/applications" },
    { id: "audit", label_message_key: "nav.audit", icon: "≡", route: "/admin/audit" },
  ] },
];

function NavContents({ collapsed = false, onNavigate }: { collapsed?: boolean; onNavigate?: () => void }) {
  const { t } = useTranslation();
  const location = useLocation();
  return <nav aria-label={t("nav.primary")} className="space-y-5 px-3 py-5">
    {navigation.map((section) => <section key={section.id} aria-label={t(section.label_message_key)}>
      <div className={cn("mb-1 flex h-8 items-center justify-between px-2 text-xs font-semibold text-muted-foreground", collapsed && "sr-only")}>
        <span>{t(section.label_message_key)}</span>
        {section.id === "administration" && <span className="rounded-sm bg-muted px-1.5 py-0.5 text-[10px] font-medium">{t("nav.roleAdmin")}</span>}
      </div>
      <div className="space-y-0.5">
        {(section.children ?? [section]).map((item) => {
          const active = item.route === location.pathname || (item.id === "tasks" && location.pathname.startsWith("/tasks/"));
          return <NavLink key={item.id} to={item.route!} onClick={onNavigate} title={collapsed ? t(item.label_message_key) : undefined}
            aria-current={active ? "page" : undefined}
            className={({ isActive }) => cn("group flex min-h-10 items-center gap-3 rounded-md px-2.5 text-sm font-medium transition-colors focus-visible:outline-none focus-visible:ring-[3px] focus-visible:ring-ring/50", isActive || active ? "bg-accent text-accent-foreground" : "text-muted-foreground hover:bg-muted hover:text-foreground", collapsed && "justify-center px-0")}>
            <span aria-hidden="true" className="flex size-5 shrink-0 items-center justify-center text-base">{item.icon}</span>
            <span className={cn("truncate", collapsed && "sr-only")}>{t(item.label_message_key)}</span>
          </NavLink>;
        })}
      </div>
    </section>)}
  </nav>;
}

export function AppShell() {
  const { t } = useTranslation();
  const { logout } = useAuth();
  const [collapsed, setCollapsed] = useState(() => localStorage.getItem("kosmo.sidebar.collapsed") === "true");
  const [drawerOpen, setDrawerOpen] = useState(false);
  const triggerRef = useRef<HTMLButtonElement>(null);
  const drawerRef = useRef<HTMLElement>(null);
  const location = useLocation();
  useEffect(() => { localStorage.setItem("kosmo.sidebar.collapsed", String(collapsed)); }, [collapsed]);
  useEffect(() => {
    if (!drawerOpen) return;
    const drawer = drawerRef.current;
    drawer?.querySelector<HTMLElement>('a[href], button:not([disabled])')?.focus();
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") { setDrawerOpen(false); triggerRef.current?.focus(); }
      if (event.key === "Tab" && drawer) {
        const nodes = [...drawer.querySelectorAll<HTMLElement>('a[href], button:not([disabled])')];
        if (!nodes.length) return;
        const first = nodes[0], last = nodes[nodes.length - 1];
        if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last.focus(); }
        else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first.focus(); }
      }
    };
    document.addEventListener("keydown", onKeyDown);
    return () => document.removeEventListener("keydown", onKeyDown);
  }, [drawerOpen]);
  useEffect(() => { setDrawerOpen(false); }, [location.pathname]);

  return <div className="flex min-h-dvh bg-background text-foreground">
    <a href="#main-content" className="sr-only focus:not-sr-only focus:fixed focus:left-3 focus:top-3 focus:z-50 focus:rounded-md focus:bg-primary focus:px-3 focus:py-2 focus:text-sm focus:text-primary-foreground">{t("app.shell.skipToContent")}</a>
    <aside className={cn("hidden shrink-0 border-r border-border bg-card/60 transition-[width] duration-200 md:block", collapsed ? "w-[4.25rem]" : "w-64")}>
      <div className={cn("sticky top-0 flex h-dvh flex-col", collapsed && "items-center")}>
        <div className={cn("flex h-14 shrink-0 items-center px-5", collapsed && "justify-center px-0")}><AppLogo className={collapsed ? "[&>span:last-child]:sr-only" : ""} /></div>
        <div className="min-h-0 flex-1 overflow-y-auto"><NavContents collapsed={collapsed} /></div>
        <button type="button" onClick={() => setCollapsed((value) => !value)} aria-label={collapsed ? t("nav.expandSidebar") : t("nav.collapseSidebar")} className="m-3 flex min-h-10 items-center justify-center gap-2 rounded-md px-3 text-sm text-muted-foreground hover:bg-muted hover:text-foreground focus-visible:outline-none focus-visible:ring-[3px] focus-visible:ring-ring/50">
          <span aria-hidden="true">{collapsed ? "›" : "‹"}</span>{!collapsed && <span>{t("nav.collapseSidebar")}</span>}
        </button>
      </div>
    </aside>
    <div className="flex min-w-0 flex-1 flex-col">
      <header className="sticky top-0 z-20 flex h-14 items-center justify-between border-b border-border bg-background px-4 sm:px-6">
        <div className="flex items-center gap-3">
          <button ref={triggerRef} type="button" onClick={() => setDrawerOpen(true)} aria-label={t("nav.openMenu")} aria-expanded={drawerOpen} className="flex size-9 items-center justify-center rounded-md text-lg hover:bg-muted focus-visible:outline-none focus-visible:ring-[3px] focus-visible:ring-ring/50 md:hidden">☰</button>
          <div className="md:hidden"><AppLogo /></div>
          <div className="hidden md:block"><span className="text-sm font-medium text-foreground">{t("app.workspace")}</span></div>
        </div>
        <div className="flex items-center gap-3"><LanguageSwitcher /><button type="button" onClick={() => void logout()} aria-label={t("auth.login.logout")} title={t("auth.login.logout")} className="flex size-9 items-center justify-center rounded-full bg-secondary text-xs font-semibold text-secondary-foreground focus-visible:outline-none focus-visible:ring-[3px] focus-visible:ring-ring/50">{t("auth.login.logout")}</button></div>
      </header>
      <main id="main-content" className="flex flex-1 flex-col"><Outlet /></main>
    </div>
    {drawerOpen && <div className="fixed inset-0 z-40 md:hidden">
      <button type="button" aria-label={t("nav.closeMenu")} onClick={() => { setDrawerOpen(false); triggerRef.current?.focus(); }} className="absolute inset-0 bg-foreground/35" />
      <aside ref={drawerRef} role="dialog" aria-modal="true" aria-label={t("nav.primary")} className="absolute inset-y-0 left-0 flex w-[min(19rem,calc(100vw-2.5rem))] flex-col border-r border-border bg-background shadow-lg">
        <div className="flex h-14 items-center justify-between border-b border-border px-5"><AppLogo /><button type="button" onClick={() => { setDrawerOpen(false); triggerRef.current?.focus(); }} aria-label={t("nav.closeMenu")} className="flex size-9 items-center justify-center rounded-md text-xl text-muted-foreground hover:bg-muted focus-visible:outline-none focus-visible:ring-[3px] focus-visible:ring-ring/50">×</button></div>
        <div className="min-h-0 flex-1 overflow-y-auto"><NavContents onNavigate={() => setDrawerOpen(false)} /></div>
      </aside>
    </div>}
  </div>;
}

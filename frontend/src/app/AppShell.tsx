import { useEffect, useRef, useState } from "react";
import { NavLink, Outlet, useLocation } from "react-router";
import { useTranslation } from "react-i18next";

import { AppLogo } from "@/components/app-logo";
import { LanguageSwitcher } from "@/features/auth/LanguageSwitcher";
import { cn } from "@/lib/utils";
import { useAuth } from "@/features/auth/AuthProvider";
import { useCurrentUser } from "@/features/auth/useCurrentUser";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { Icon, type MaterialIconName } from "@/components/ui/icon";

type NavLabelKey = "nav.tasks" | "nav.newTask" | "nav.history" | "nav.workspace" | "nav.workflows" | "nav.applications" | "nav.context" | "nav.catalog" | "nav.administration" | "nav.agents" | "nav.mcps" | "nav.skills" | "nav.extensions" | "nav.providers" | "nav.audit" | "nav.globalSettings";
type NavItem = { id: string; label_message_key: NavLabelKey; icon: MaterialIconName; route?: string; children?: NavItem[] };
export const navigation: NavItem[] = [
  { id: "tasks", label_message_key: "nav.tasks", icon: "tasks", children: [
    { id: "new-task", label_message_key: "nav.newTask", icon: "add", route: "/tasks/new" },
    { id: "history", label_message_key: "nav.history", icon: "history", route: "/tasks/history" },
  ] },
  { id: "workspace", label_message_key: "nav.workspace", icon: "workspace", children: [
    { id: "workflows", label_message_key: "nav.workflows", icon: "workflows", route: "/workflows" },
    { id: "applications", label_message_key: "nav.applications", icon: "applications", route: "/applications" },
    { id: "context", label_message_key: "nav.context", icon: "context", route: "/context" },
  ] },
  { id: "catalog", label_message_key: "nav.catalog", icon: "catalog", children: [
    { id: "agents", label_message_key: "nav.agents", icon: "agents", route: "/admin/agents" },
    { id: "mcps", label_message_key: "nav.mcps", icon: "mcp", route: "/admin/mcps" },
    { id: "skills", label_message_key: "nav.skills", icon: "skills", route: "/admin/skills" },
    { id: "extensions", label_message_key: "nav.extensions", icon: "extensions", route: "/admin/extensions" },
    { id: "providers", label_message_key: "nav.providers", icon: "providers", route: "/providers" },
  ] },
  { id: "administration", label_message_key: "nav.administration", icon: "administration", children: [
    { id: "audit", label_message_key: "nav.audit", icon: "audit", route: "/admin/audit" },
    { id: "global-settings", label_message_key: "nav.globalSettings", icon: "settings", route: "/admin/settings" },
  ] },
];

function NavContents({ collapsed = false, onNavigate }: { collapsed?: boolean; onNavigate?: () => void }) {
  const { t } = useTranslation();
  const location = useLocation();
  return <nav aria-label={t("nav.primary")} className="space-y-5 px-3 py-5">
    {navigation.map((section) => <section key={section.id} aria-label={t(section.label_message_key)}>
      <div className={cn("mb-1 flex h-8 items-center justify-between px-2 text-xs font-semibold text-muted-foreground", collapsed && "sr-only")}>
        <span>{t(section.label_message_key)}</span>
      </div>
      <div className="space-y-0.5">
        {(section.children ?? [section]).map((item) => {
          const active = item.route === location.pathname || (item.id === "tasks" && location.pathname.startsWith("/tasks/"));
          return <NavLink key={item.id} to={item.route!} onClick={onNavigate} title={collapsed ? t(item.label_message_key) : undefined}
            aria-current={active ? "page" : undefined}
            className={({ isActive }) => cn("group flex min-h-10 items-center gap-3 rounded-md px-2.5 text-sm font-medium transition-colors focus-visible:outline-none focus-visible:ring-[3px] focus-visible:ring-ring/50", isActive || active ? "bg-accent text-accent-foreground" : "text-muted-foreground hover:bg-muted hover:text-foreground", collapsed && "justify-center px-0")}>
            <span aria-hidden="true" className="flex size-5 shrink-0 items-center justify-center"><Icon name={item.icon} /></span>
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
  const { user } = useCurrentUser();
  const [collapsed, setCollapsed] = useState(() => localStorage.getItem("kosmo.sidebar.collapsed") === "true");
  const [drawerOpen, setDrawerOpen] = useState(false);
  const [userMenuOpen, setUserMenuOpen] = useState(false);
  const triggerRef = useRef<HTMLButtonElement>(null);
  const drawerRef = useRef<HTMLElement>(null);
  const location = useLocation();
  // Uppercase first character of the authenticated username; null while the
  // user is pending or errored, which renders the neutral fallback avatar.
  const username = user?.username?.trim();
  const initial = username ? username.charAt(0).toUpperCase() : null;
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
  // Route transitions dismiss transient shell layers (mobile drawer and the
  // header user menu) so neither survives into the next page.
  useEffect(() => { setDrawerOpen(false); setUserMenuOpen(false); }, [location.pathname]);

  return <div className="flex min-h-dvh bg-background text-foreground">
    <a href="#main-content" className="sr-only focus:not-sr-only focus:fixed focus:left-3 focus:top-3 focus:z-50 focus:rounded-md focus:bg-primary focus:px-3 focus:py-2 focus:text-sm focus:text-primary-foreground">{t("app.shell.skipToContent")}</a>
    <aside className={cn("hidden shrink-0 border-r border-border bg-card/60 transition-[width] duration-200 md:block", collapsed ? "w-[4.25rem]" : "w-64")}>
      <div className={cn("sticky top-0 flex h-dvh flex-col", collapsed && "items-center")}>
        <div className={cn("flex h-14 shrink-0 items-center px-5", collapsed && "justify-center px-0")}><AppLogo className={collapsed ? "[&>span:last-child]:sr-only" : ""} /></div>
        <div className="min-h-0 flex-1 overflow-y-auto"><NavContents collapsed={collapsed} /></div>
        <button type="button" onClick={() => setCollapsed((value) => !value)} aria-label={collapsed ? t("nav.expandSidebar") : t("nav.collapseSidebar")} className="m-3 flex min-h-10 items-center justify-center gap-2 rounded-full px-3 text-sm text-muted-foreground hover:bg-muted hover:text-foreground focus-visible:outline-none focus-visible:ring-[3px] focus-visible:ring-ring/50">
          <Icon name={collapsed ? "sidebarExpand" : "sidebarCollapse"} />{!collapsed && <span>{t("nav.collapseSidebar")}</span>}
        </button>
      </div>
    </aside>
    <div className="flex min-w-0 flex-1 flex-col">
      <header className="sticky top-0 z-20 flex h-14 items-center justify-between border-b border-border bg-background px-4 sm:px-6">
        <div className="flex items-center gap-3">
          <button ref={triggerRef} type="button" onClick={() => setDrawerOpen(true)} aria-label={t("nav.openMenu")} aria-expanded={drawerOpen} className="flex size-9 items-center justify-center rounded-full hover:bg-muted focus-visible:outline-none focus-visible:ring-[3px] focus-visible:ring-ring/50 md:hidden"><Icon name="openMenu" /></button>
          <div className="md:hidden"><AppLogo /></div>
          <div className="hidden md:block"><span className="text-sm font-medium text-foreground">{t("app.workspace")}</span></div>
        </div>
        <div className="flex items-center gap-3">
          <LanguageSwitcher />
          <DropdownMenu open={userMenuOpen} onOpenChange={setUserMenuOpen}>
            <DropdownMenuTrigger asChild>
              <button type="button" aria-label={t("app.userMenu")} className="flex size-9 items-center justify-center rounded-full bg-secondary text-xs font-semibold text-secondary-foreground hover:bg-secondary/80 focus-visible:outline-none focus-visible:ring-[3px] focus-visible:ring-ring/50">
                {initial ? <span aria-hidden="true">{initial}</span> : <Icon name="userMenu" size={20} />}
              </button>
            </DropdownMenuTrigger>
            <DropdownMenuContent align="end">
              <DropdownMenuItem onSelect={() => void logout()}>
                <Icon name="logout" />
                {t("auth.login.logout")}
              </DropdownMenuItem>
            </DropdownMenuContent>
          </DropdownMenu>
        </div>
      </header>
      <main id="main-content" className="flex flex-1 flex-col"><Outlet /></main>
    </div>
    {drawerOpen && <div className="fixed inset-0 z-40 md:hidden">
      <button type="button" aria-label={t("nav.closeMenu")} onClick={() => { setDrawerOpen(false); triggerRef.current?.focus(); }} className="absolute inset-0 bg-foreground/35" />
      <aside ref={drawerRef} role="dialog" aria-modal="true" aria-label={t("nav.primary")} className="absolute inset-y-0 left-0 flex w-[min(19rem,calc(100vw-2.5rem))] flex-col border-r border-border bg-background shadow-lg">
        <div className="flex h-14 items-center justify-between border-b border-border px-5"><AppLogo /><button type="button" onClick={() => { setDrawerOpen(false); triggerRef.current?.focus(); }} aria-label={t("nav.closeMenu")} className="flex size-9 items-center justify-center rounded-full text-muted-foreground hover:bg-muted focus-visible:outline-none focus-visible:ring-[3px] focus-visible:ring-ring/50"><Icon name="close" /></button></div>
        <div className="min-h-0 flex-1 overflow-y-auto"><NavContents onNavigate={() => setDrawerOpen(false)} /></div>
      </aside>
    </div>}
  </div>;
}

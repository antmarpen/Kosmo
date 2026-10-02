import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { AppRoutes } from "./router";
import { changeLanguage } from "@/i18n";
import { AuthProvider } from "@/features/auth/AuthProvider";
import { clearTokens, setTokens } from "@/api/auth";
import { ICON_NAMES } from "@/components/ui/icon-names";

// Controllable useCurrentUser mock: the real hook fetches /auth/me and
// /auth/capabilities on mount, which no shell test should depend on. The
// beforeEach default is an authenticated user; individual tests override it
// through setUser to exercise the pending/error fallback.
const currentUserState = vi.hoisted(() => ({
  user: null as { username: string } | null,
  loading: false,
  error: null as Error | null,
}));
vi.mock("@/features/auth/useCurrentUser", () => ({
  useCurrentUser: () => ({
    user: currentUserState.user,
    capabilities: null,
    loading: currentUserState.loading,
    error: currentUserState.error,
  }),
}));

// logoutRequest performs a real network call; resolve it so sign-out flows
// complete inside jsdom while the rest of the auth module stays original.
const { logoutRequest } = vi.hoisted(() => ({
  logoutRequest: vi.fn().mockResolvedValue(undefined),
}));
vi.mock("@/api/auth", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/api/auth")>()),
  logoutRequest,
}));

// jsdom does not implement ResizeObserver, which Radix popper-based content
// (the user menu) measures with. Same no-op stub convention as
// dropdown-menu.test.tsx.
class ResizeObserverStub {
  observe() {}
  unobserve() {}
  disconnect() {}
}
vi.stubGlobal("ResizeObserver", ResizeObserverStub);

function renderAt(path = "/") {
  if (path === "/login") clearTokens(); else setTokens("test-access", "test-refresh");
  return render(<AuthProvider><MemoryRouter initialEntries={[path]}><AppRoutes /></MemoryRouter></AuthProvider>);
}

function setUser(user: { username: string } | null, options: { loading?: boolean; error?: Error | null } = {}) {
  currentUserState.user = user;
  currentUserState.loading = options.loading ?? user === null;
  currentUserState.error = options.error ?? null;
}

beforeEach(() => {
  setUser({ username: "alex" });
});

afterEach(() => {
  logoutRequest.mockClear();
});

describe("app shell and routes", () => {
  it("lands on the live task list and provides the shell", async () => {
    renderAt();
    changeLanguage("en");
    expect(await screen.findByRole("heading", { level: 1, name: "Tasks" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Add" })).toHaveAttribute("href", "/tasks/new");
    expect(screen.getByRole("group", { name: "Language" })).toBeInTheDocument();
    expect(screen.getByText("Skip to content")).toBeInTheDocument();
  });

  it.each(["en", "es"])("renders the configuration navigation in %s", async (language) => {
    changeLanguage(language as "en" | "es");
    renderAt("/tasks/new");
    const labels = language === "en"
      ? ["Workspace", "Catalog", "Workflows", "Applications", "Context", "Agents", "MCPs", "Skills", "Extensions", "Providers", "Administration", "Audit", "Global settings"]
      : ["Espacio de trabajo", "Catálogo", "Flujos de trabajo", "Aplicaciones", "Contexto", "Agentes", "MCP", "Habilidades", "Extensiones", "Proveedores", "Administración", "Auditoría", "Configuración global"];
    for (const label of labels) expect(screen.getAllByText(label).length).toBeGreaterThan(0);
    const mainNav = screen.getByRole("navigation", { name: language === "en" ? "Main navigation" : "Navegación principal" });
    for (const path of ["/workflows", "/applications", "/context", "/admin/agents", "/admin/mcps", "/admin/skills", "/admin/extensions", "/providers", "/admin/audit", "/admin/settings"]) {
      expect(mainNav.querySelector(`a[href="${path}"]`)).toBeInTheDocument();
    }
    const catalog = screen.getByRole("region", { name: language === "en" ? "Catalog" : "Catálogo" });
    expect(catalog.querySelectorAll("a")).toHaveLength(5);
    const workspace = screen.getByRole("region", { name: language === "en" ? "Workspace" : "Espacio de trabajo" });
    expect(workspace.querySelectorAll("a")).toHaveLength(3);
    const administration = screen.getByRole("region", { name: language === "en" ? "Administration" : "Administración" });
    expect(administration.querySelectorAll("a")).toHaveLength(2);
    for (const path of ["/admin/agents", "/admin/mcps", "/admin/skills", "/admin/extensions", "/providers"]) {
      expect(administration.querySelector(`a[href="${path}"]`)).not.toBeInTheDocument();
    }
    changeLanguage("en");
  });

  it("renders navigation and shell controls from the Material Symbols registry instead of unicode glyphs", () => {
    renderAt("/");
    const nav = screen.getByRole("navigation", { name: "Main navigation" });
    // Only child items (and top-level items without children) render an
    // icon; group headers with children show no icon of their own.
    for (const ligature of [
      ICON_NAMES.add, ICON_NAMES.history,
      ICON_NAMES.workflows, ICON_NAMES.applications, ICON_NAMES.context,
      ICON_NAMES.agents, ICON_NAMES.mcp, ICON_NAMES.skills, ICON_NAMES.extensions, ICON_NAMES.providers,
      ICON_NAMES.audit, ICON_NAMES.settings,
    ]) {
      expect(within(nav).getAllByText(ligature).length).toBeGreaterThan(0);
    }
    // Shell controls: mobile menu trigger and the expanded sidebar's collapse
    // control both render registry ligatures.
    expect(screen.getAllByText(ICON_NAMES.openMenu).length).toBeGreaterThan(0);
    expect(screen.getAllByText(ICON_NAMES.sidebarCollapse).length).toBeGreaterThan(0);
    // The hand-picked unicode glyph icons are gone from the whole shell.
    for (const glyph of ["▤", "+", "◷", "▦", "⌘", "▣", "◇", "❖", "◉", "⇄", "✳", "⊞", "◈", "⚙", "≡", "›", "‹", "☰", "×"]) {
      expect(screen.queryAllByText(glyph)).toHaveLength(0);
    }
  });

  it("renders the drawer close control from the registry", async () => {
    const user = userEvent.setup();
    renderAt("/tasks/new");
    await user.click(screen.getByRole("button", { name: "Open navigation menu" }));
    const drawer = screen.getByRole("dialog", { name: "Main navigation" });
    expect(within(drawer).getByText(ICON_NAMES.close)).toBeInTheDocument();
  });

  it("shows the uppercase initial of the authenticated user in the avatar", () => {
    setUser({ username: "alex" });
    renderAt("/");
    const avatar = screen.getByRole("button", { name: "User menu" });
    expect(avatar).toHaveTextContent("A");
  });

  it("keeps a neutral fixed-size avatar while the user is pending or errored", () => {
    setUser(null);
    renderAt("/");
    const avatar = screen.getByRole("button", { name: "User menu" });
    // No initial can be derived: no letter, just the neutral fallback icon.
    expect(avatar).not.toHaveTextContent("A");
    expect(within(avatar).getByText(ICON_NAMES.userMenu)).toBeInTheDocument();
    // Fixed circular size in the fallback state: no layout shift.
    expect(avatar).toHaveClass("size-9", "rounded-full");
  });

  it("opens the user menu with the correct ARIA state, a single sign-out item, and closes on Escape", async () => {
    const user = userEvent.setup();
    renderAt("/");
    const avatar = screen.getByRole("button", { name: "User menu" });
    expect(avatar).toHaveAttribute("aria-haspopup", "menu");
    expect(avatar).toHaveAttribute("aria-expanded", "false");

    await user.click(avatar);

    expect(avatar).toHaveAttribute("aria-expanded", "true");
    expect(screen.getByRole("menuitem", { name: "Sign out" })).toBeInTheDocument();
    expect(screen.getAllByRole("menuitem")).toHaveLength(1);

    await user.keyboard("{Escape}");

    await waitFor(() => expect(screen.queryByRole("menuitem", { name: "Sign out" })).not.toBeInTheDocument());
    expect(avatar).toHaveAttribute("aria-expanded", "false");
    expect(avatar).toHaveFocus();
  });

  it("signs out from the user menu and lands on the login page", async () => {
    const user = userEvent.setup();
    renderAt("/");
    await user.click(screen.getByRole("button", { name: "User menu" }));
    await user.click(screen.getByRole("menuitem", { name: "Sign out" }));
    expect(await screen.findByRole("heading", { level: 1, name: "Sign in" })).toBeInTheDocument();
    expect(logoutRequest).toHaveBeenCalledTimes(1);
  });

  it("closes the user menu when the route changes", async () => {
    const user = userEvent.setup();
    renderAt("/");
    await user.click(screen.getByRole("button", { name: "User menu" }));
    expect(screen.getByRole("menuitem", { name: "Sign out" })).toBeInTheDocument();
    // The open modal menu marks the rest of the page aria-hidden, so the
    // sidebar link is only reachable with hidden: true; and it sets
    // pointer-events: none on body, so a pointer event cannot reach it.
    // Fire the navigation directly to simulate the route transition.
    fireEvent.click(screen.getByRole("link", { name: "Workflows", hidden: true }));
    await waitFor(() => expect(screen.queryByRole("menuitem", { name: "Sign out" })).not.toBeInTheDocument());
    expect(screen.getByRole("button", { name: "User menu" })).toHaveAttribute("aria-expanded", "false");
  });

  it("opens the mobile drawer, closes with Escape, and returns focus", async () => {
    const user = userEvent.setup();
    renderAt("/tasks/new");
    const trigger = screen.getByRole("button", { name: "Open navigation menu" });
    await user.click(trigger);
    expect(screen.getByRole("dialog", { name: "Main navigation" })).toBeInTheDocument();
    await user.keyboard("{Escape}");
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    expect(trigger).toHaveFocus();
  });

  it("traps keyboard focus within the drawer", async () => {
    const user = userEvent.setup();
    renderAt("/tasks/new");
    await user.click(screen.getByRole("button", { name: "Open navigation menu" }));
    const drawer = screen.getByRole("dialog");
    const controls = drawer.querySelectorAll("a[href], button:not([disabled])");
    expect(controls[0]).toHaveFocus();
    await user.keyboard("{Shift>}{Tab}{/Shift}");
    expect(controls[controls.length - 1]).toHaveFocus();
    await user.keyboard("{Tab}");
    expect(controls[0]).toHaveFocus();
  });

  it("closes the drawer after navigation and persists sidebar collapse", async () => {
    const user = userEvent.setup();
    renderAt("/tasks/new");
    await user.click(screen.getByRole("button", { name: "Open navigation menu" }));
    const historyLink = screen.getAllByRole("link", { name: "History" }).find((link) => link.closest('[role="dialog"]'));
    expect(historyLink).toBeDefined();
    await user.click(historyLink!);
    expect(await screen.findByRole("heading", { name: "History" })).toBeInTheDocument();
    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
    await user.click(screen.getByRole("button", { name: "Collapse sidebar" }));
    await waitFor(() => expect(localStorage.getItem("kosmo.sidebar.collapsed")).toBe("true"));
  });

  it("renders the login page outside the shell", () => {
    renderAt("/login");
    expect(screen.getByRole("heading", { level: 1, name: "Sign in" })).toBeInTheDocument();
    expect(screen.getByLabelText("Username")).toBeInTheDocument();
  });
});

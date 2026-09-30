import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router";
import { describe, expect, it } from "vitest";

import { AppRoutes } from "./router";
import { changeLanguage } from "@/i18n";
import { AuthProvider } from "@/features/auth/AuthProvider";
import { clearTokens, setTokens } from "@/api/auth";

function renderAt(path = "/") {
  if (path === "/login") clearTokens(); else setTokens("test-access", "test-refresh");
  return render(<AuthProvider><MemoryRouter initialEntries={[path]}><AppRoutes /></MemoryRouter></AuthProvider>);
}

describe("app shell and routes", () => {
  it("lands on the live task list and provides the shell", async () => {
    renderAt();
    changeLanguage("en");
    expect(await screen.findByRole("heading", { level: 1, name: "Tasks" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Create task" })).toHaveAttribute("href", "/tasks/new");
    expect(screen.getByRole("group", { name: "Language" })).toBeInTheDocument();
    expect(screen.getByText("Skip to content")).toBeInTheDocument();
  });

  it.each(["en", "es"])("renders every navigation item in %s", async (language) => {
    changeLanguage(language as "en" | "es");
    renderAt("/tasks/new");
    const labels = language === "en"
      ? ["Tasks", "New task", "History", "Workflows", "Context", "Administration", "Agents", "MCPs", "Skills", "Extensions", "Repositories", "Applications", "Audit"]
      : ["Tareas", "Nueva tarea", "Historial", "Flujos de trabajo", "Contexto", "Administración", "Agentes", "MCP", "Habilidades", "Extensiones", "Repositorios", "Aplicaciones", "Auditoría"];
    for (const label of labels) expect(screen.getAllByText(label).length).toBeGreaterThan(0);
    changeLanguage("en");
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

import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { MemoryRouter } from "react-router";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { clearTokens } from "@/api/auth";
import { LANGUAGE_STORAGE_KEY } from "@/i18n";
import { LoginPage } from "./LoginPage";
import { AuthProvider } from "./AuthProvider";

function renderLogin() { return render(<AuthProvider><MemoryRouter><LoginPage /></MemoryRouter></AuthProvider>); }

const EN = {
  title: "Sign in",
  subtitle: "Access your Kosmo workspace.",
  username: "Username",
  password: "Password",
  action: "Sign in",
  pending: "Signing in…",
  error: "Sign-in failed. Check your username and password.",
};

const ES = {
  title: "Iniciar sesión",
  subtitle: "Accede a tu espacio de trabajo Kosmo.",
  username: "Usuario",
  password: "Contraseña",
  action: "Iniciar sesión",
};

async function switchTo(language: "English" | "Español") {
  const user = userEvent.setup();
  await user.click(screen.getByRole("button", { name: language }));
}

/** Number of login POST requests issued through the mocked transport. */
function loginCallCount(calls: unknown[][]) {
  return calls.filter((call) => call[0] instanceof Request && (call[0] as Request).url.endsWith("/auth/login")).length;
}

describe("LoginPage", () => {
  beforeEach(() => {
    window.localStorage.clear();
    clearTokens();
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("renders the login form with English strings by default", () => {
    renderLogin();

    expect(screen.getByRole("heading", { level: 1, name: EN.title })).toBeInTheDocument();
    expect(screen.getByText(EN.subtitle)).toBeInTheDocument();
    expect(screen.getByLabelText(EN.username)).toBeInTheDocument();
    expect(screen.getByLabelText(EN.password)).toHaveAttribute("type", "password");
    expect(screen.getByRole("button", { name: EN.action })).toBeInTheDocument();
    // The submit action carries a representative leading icon.
    const submitButton = screen.getByRole("button", { name: EN.action });
    expect(submitButton.querySelector('[data-slot="icon"]')).not.toBeNull();
    // Brand mark and wordmark are visible.
    expect(screen.getAllByText("Kosmo").length).toBeGreaterThan(0);
  });

  it("swaps every visible string to Spanish when the switcher is used", async () => {
    renderLogin();
    await switchTo("Espa\u00f1ol");

    expect(screen.getByRole("heading", { level: 1, name: ES.title })).toBeInTheDocument();
    expect(screen.getByText(ES.subtitle)).toBeInTheDocument();
    expect(screen.getByLabelText(ES.username)).toBeInTheDocument();
    expect(screen.getByLabelText(ES.password)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: ES.action })).toBeInTheDocument();

    // The English strings are gone.
    expect(
      screen.queryByRole("heading", { level: 1, name: EN.title }),
    ).not.toBeInTheDocument();
    expect(screen.queryByLabelText(EN.username)).not.toBeInTheDocument();
  });

  it("swaps back to English", async () => {
    renderLogin();
    await switchTo("Espa\u00f1ol");
    await switchTo("English");

    expect(screen.getByRole("heading", { level: 1, name: EN.title })).toBeInTheDocument();
    expect(screen.getByLabelText(EN.username)).toBeInTheDocument();
  });

  it("persists the chosen language in localStorage", async () => {
    renderLogin();
    await switchTo("Espa\u00f1ol");
    expect(window.localStorage.getItem(LANGUAGE_STORAGE_KEY)).toBe("es");

    await switchTo("English");
    expect(window.localStorage.getItem(LANGUAGE_STORAGE_KEY)).toBe("en");
  });

  it("keeps each language option labeled in its own language", () => {
    renderLogin();
    expect(screen.getByRole("button", { name: "English" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Español" })).toBeInTheDocument();
  });

  it("uses a fluid mobile-first layout with no fixed-width column (responsive smoke)", () => {
    const { container } = renderLogin();

    const root = container.firstElementChild as HTMLElement;
    expect(root).toHaveClass("min-h-dvh");

    // The form column is fluid up to its max width.
    const column = container.querySelector<HTMLElement>(".max-w-sm");
    expect(column).not.toBeNull();
    expect(column).toHaveClass("w-full");

    // The submit button spans the full column width.
    expect(screen.getByRole("button", { name: EN.action })).toHaveClass("w-full");

    // No element pins a fixed pixel/rem width that would overflow at 375px.
    expect(container.innerHTML).not.toMatch(/w-\[\d+(px|rem)\]/);
  });

  it("keeps the action label and shows busy feedback while signing in", async () => {
    let resolveLogin!: (response: Response) => void;
    const fetchMock = vi.spyOn(globalThis, "fetch").mockImplementation(
      () => new Promise<Response>((resolve) => { resolveLogin = resolve; }),
    );
    renderLogin();
    fireEvent.change(screen.getByLabelText(EN.username), { target: { value: "admin" } });
    fireEvent.change(screen.getByLabelText(EN.password), { target: { value: "secret" } });
    fireEvent.submit(screen.getByRole("form", { name: EN.title }));

    // The label is unchanged while in flight — no separate "Signing in…" string.
    const button = screen.getByRole("button", { name: EN.action });
    expect(screen.queryByText(EN.pending)).not.toBeInTheDocument();
    expect(button).toBeDisabled();
    expect(button).toHaveAttribute("aria-busy", "true");
    // The shared Button renders its decorative spinner.
    expect(within(button).getByText("progress_activity")).toBeInTheDocument();

    await waitFor(() => expect(loginCallCount(fetchMock.mock.calls)).toBe(1));
    resolveLogin(new Response(JSON.stringify({ detail: "Invalid credentials" }), { status: 401, headers: { "Content-Type": "application/json" } }));
    await waitFor(() => expect(button).toBeEnabled());
  });

  it("does not call the login API twice on duplicate submits while pending", async () => {
    const fetchMock = vi.spyOn(globalThis, "fetch").mockImplementation(
      () => new Promise<Response>(() => undefined),
    );
    renderLogin();
    fireEvent.change(screen.getByLabelText(EN.username), { target: { value: "admin" } });
    fireEvent.change(screen.getByLabelText(EN.password), { target: { value: "secret" } });
    fireEvent.submit(screen.getByRole("form", { name: EN.title }));
    await waitFor(() => expect(loginCallCount(fetchMock.mock.calls)).toBe(1));

    // The busy submit button is disabled, so a second activation attempt is swallowed.
    const button = screen.getByRole("button", { name: EN.action });
    expect(button).toBeDisabled();
    fireEvent.click(button);
    expect(loginCallCount(fetchMock.mock.calls)).toBe(1);
  });

  it("re-enables and shows the localized error when sign-in fails", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response(JSON.stringify({ detail: "Invalid credentials" }), { status: 401, headers: { "Content-Type": "application/json" } }),
    );
    renderLogin();
    fireEvent.change(screen.getByLabelText(EN.username), { target: { value: "admin" } });
    fireEvent.change(screen.getByLabelText(EN.password), { target: { value: "secret" } });
    fireEvent.submit(screen.getByRole("form", { name: EN.title }));

    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent(EN.error);
    const button = screen.getByRole("button", { name: EN.action });
    expect(button).toBeEnabled();
    expect(button).not.toHaveAttribute("aria-busy");
  });
});


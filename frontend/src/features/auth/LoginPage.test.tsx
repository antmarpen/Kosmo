import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it } from "vitest";

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

describe("LoginPage", () => {
  beforeEach(() => {
    window.localStorage.clear();
  });

  it("renders the login form with English strings by default", () => {
    renderLogin();

    expect(screen.getByRole("heading", { level: 1, name: EN.title })).toBeInTheDocument();
    expect(screen.getByText(EN.subtitle)).toBeInTheDocument();
    expect(screen.getByLabelText(EN.username)).toBeInTheDocument();
    expect(screen.getByLabelText(EN.password)).toHaveAttribute("type", "password");
    expect(screen.getByRole("button", { name: EN.action })).toBeInTheDocument();
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
});


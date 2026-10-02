import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { Icon } from "./icon";
import { ICON_NAMES } from "./icon-names";

describe("Icon", () => {
  it("renders the Material Symbols Rounded ligature for a registry name", () => {
    render(<Icon name="tasks" />);
    // "tasks" maps to the "checklist" ligature in the registry.
    const icon = screen.getByText(ICON_NAMES.tasks);
    expect(icon).toHaveClass("material-symbols-rounded");
  });

  it("is decorative by default: hidden from the accessibility tree with no accessible name", () => {
    render(<Icon name="delete" />);
    const icon = screen.getByText("delete");
    expect(icon).toHaveAttribute("aria-hidden", "true");
    expect(icon).not.toHaveAttribute("role");
    expect(icon).not.toHaveAttribute("aria-label");
    // No accessible name of any kind, so the ligature text can never leak.
    expect(screen.queryByRole("img")).toBeNull();
    expect(icon).not.toHaveAccessibleName();
  });

  it("exposes the label — not the ligature text — as the accessible name", () => {
    render(<Icon name="delete" label="Delete provider" />);
    const icon = screen.getByRole("img");
    expect(icon).toHaveAccessibleName("Delete provider");
    // The ligature name must not become the accessible name.
    expect(icon).not.toHaveAccessibleName("delete");
  });

  it("treats an empty label as decorative", () => {
    render(<Icon name="check" label="" />);
    expect(screen.queryByRole("img")).toBeNull();
    expect(screen.getByText("check")).toHaveAttribute("aria-hidden", "true");
  });

  it("applies a numeric size as inline font-size", () => {
    render(<Icon name="settings" size={32} />);
    expect(screen.getByText("settings")).toHaveStyle({ fontSize: "32px" });
  });

  it("defaults to a 20px outline icon", () => {
    render(<Icon name="info" />);
    const icon = screen.getByText("info");
    expect(icon).toHaveStyle({ fontSize: "20px" });
    expect(icon).toHaveStyle({
      fontVariationSettings: "'FILL' 0, 'wght' 400, 'GRAD' 0, 'opsz' 20",
    });
  });

  it("applies fill and weight through font-variation-settings", () => {
    render(<Icon name="info" fill weight={600} />);
    expect(screen.getByText("info")).toHaveStyle({
      fontVariationSettings: "'FILL' 1, 'wght' 600, 'GRAD' 0, 'opsz' 20",
    });
  });

  it("merges consumer className and style on top of the defaults", () => {
    render(
      <Icon
        name="send"
        className="animate-spin text-primary"
        style={{ color: "rgb(18, 52, 86)" }}
      />
    );
    const icon = screen.getByText("send");
    expect(icon).toHaveClass("material-symbols-rounded", "animate-spin");
    expect(icon).toHaveStyle({ color: "rgb(18, 52, 86)" });
  });

  it("accepts a CSS size string", () => {
    render(<Icon name="history" size="1.5rem" />);
    // jsdom normalizes rem in computed styles, so assert on the emitted
    // inline style attribute.
    const icon = screen.getByText("history");
    expect(icon.getAttribute("style")).toContain("font-size: 1.5rem");
  });
});

describe("ICON_NAMES registry", () => {
  it("covers the shell navigation and action vocabulary", () => {
    for (const key of [
      "tasks",
      "add",
      "history",
      "workspace",
      "workflows",
      "applications",
      "context",
      "catalog",
      "agents",
      "mcp",
      "skills",
      "extensions",
      "providers",
      "administration",
      "audit",
      "settings",
      "sidebarCollapse",
      "sidebarExpand",
      "openMenu",
      "close",
      "logout",
      "userMenu",
      "edit",
      "delete",
      "stop",
      "send",
      "save",
      "check",
      "error",
      "spinner",
      "info",
    ] as const) {
      expect(ICON_NAMES, `missing registry key: ${key}`).toHaveProperty(key);
      expect(typeof ICON_NAMES[key]).toBe("string");
    }
  });
});

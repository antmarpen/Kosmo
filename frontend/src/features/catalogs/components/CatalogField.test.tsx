import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";

import { Input } from "@/components/ui/input";

import { CatalogField, CatalogTextArea } from "./CatalogField";

describe("CatalogField", () => {
  it("associates the label with its control so the field is announced", () => {
    render(
      <CatalogField label="Name">
        <Input defaultValue="" />
      </CatalogField>,
    );
    const control = screen.getByLabelText("Name");
    expect(control.tagName).toBe("INPUT");
  });

  it("exposes the hint through the control's description", () => {
    render(
      <CatalogField label="Name" hint="Shown in the catalog list.">
        <Input defaultValue="" />
      </CatalogField>,
    );
    const control = screen.getByLabelText("Name");
    const describedBy = control.getAttribute("aria-describedby");
    expect(describedBy).toBeTruthy();
    const hint = screen.getByText("Shown in the catalog list.");
    expect(describedBy).toContain(hint.id);
  });

  it("marks the control invalid and announces the error when present", () => {
    render(
      <CatalogField label="Name" error="A name is required.">
        <Input defaultValue="" />
      </CatalogField>,
    );
    const control = screen.getByLabelText("Name");
    expect(control).toHaveAttribute("aria-invalid", "true");
    const alert = screen.getByRole("alert");
    expect(alert).toHaveTextContent("A name is required.");
    const describedBy = control.getAttribute("aria-describedby");
    expect(describedBy).toContain(alert.id);
  });

  it("keeps an explicitly supplied control id instead of generating one", () => {
    render(
      <CatalogField label="Name">
        <Input id="agent-name" defaultValue="" />
      </CatalogField>,
    );
    expect(screen.getByLabelText("Name")).toHaveAttribute("id", "agent-name");
  });

  it("wires a textarea variant with a mono instructions editor", async () => {
    const user = userEvent.setup();
    render(
      <CatalogField label="Instructions">
        <CatalogTextArea rows={4} />
      </CatalogField>,
    );
    const control = screen.getByLabelText("Instructions");
    expect(control.tagName).toBe("TEXTAREA");
    await user.type(control, "# Hello");
    expect(control).toHaveValue("# Hello");
  });
});

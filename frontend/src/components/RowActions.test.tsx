import * as React from "react";
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { Link, MemoryRouter, Route, Routes, useLocation } from "react-router";
import { describe, expect, it, vi } from "vitest";

import { RowActionButton, RowActionLink, RowActions } from "./RowActions";

// jsdom does not implement ResizeObserver, which Radix popper-based content
// measures with. Same no-op stub convention as tooltip.test.tsx.
class ResizeObserverStub {
  observe() {}
  unobserve() {}
  disconnect() {}
}
vi.stubGlobal("ResizeObserver", ResizeObserverStub);

// All user-facing strings arrive as props (the consuming feature passes
// localized catalog values); the tests mirror that contract with literals.

// Always rendered inside the router (as a `Routes` sibling) so a test can
// assert both that navigation happened and that it did not.
function LocationProbe() {
  const location = useLocation();
  return <div data-testid="location">{location.pathname}</div>;
}

function renderRoutes(element: React.ReactElement) {
  return render(
    <MemoryRouter initialEntries={["/workflows"]}>
      <Routes>
        <Route path="/workflows" element={element} />
        <Route path="/workflows/:id/edit" element={null} />
      </Routes>
      <LocationProbe />
    </MemoryRouter>,
  );
}

describe("RowActions", () => {
  it("renders a right-aligned named group around the supplied actions", () => {
    render(
      <RowActions aria-label="Workflow actions">
        <RowActionButton icon="edit" label="Edit" onClick={() => undefined} />
      </RowActions>,
    );

    const group = screen.getByRole("group", { name: "Workflow actions" });
    // Right-aligned presentation: trailing auto margin in flex rows plus
    // right justification inside the group itself.
    expect(group).toHaveClass("ml-auto", "flex", "items-center", "justify-end");
    expect(within(group).getByRole("button", { name: "Edit" })).toBeInTheDocument();
  });
});

describe("RowActionButton", () => {
  it("names the icon action from the label prop and keeps the icon decorative", () => {
    render(<RowActionButton icon="edit" label="Edit workflow" tooltip="Opens the editor" />);

    const button = screen.getByRole("button", { name: "Edit workflow" });
    expect(button).toHaveAccessibleName("Edit workflow");
    // Shared 36px touch target (Button size="icon").
    expect(button).toHaveClass("size-9");
    const icon = button.querySelector('[data-slot="icon"]');
    expect(icon).toHaveAttribute("aria-hidden", "true");
  });

  it("shows the tooltip on keyboard focus without replacing the accessible name", async () => {
    const user = userEvent.setup();
    render(<RowActionButton icon="edit" label="Edit workflow" tooltip="Opens the editor" />);

    await user.tab();

    const tooltip = await screen.findByRole("tooltip");
    expect(tooltip).toHaveTextContent("Opens the editor");
    const trigger = screen.getByRole("button", { name: "Edit workflow" });
    expect(trigger).toHaveAttribute("aria-describedby", tooltip.id);
    expect(trigger).toHaveAccessibleName("Edit workflow");
  });

  it("falls back to the label as tooltip text when no tooltip prop is given", async () => {
    const user = userEvent.setup();
    render(<RowActionButton icon="delete" label="Delete provider" />);

    await user.tab();

    const tooltip = await screen.findByRole("tooltip");
    expect(tooltip).toHaveTextContent("Delete provider");
  });

  it("fires onClick when enabled and suppresses it when disabled", async () => {
    const user = userEvent.setup();
    const onClick = vi.fn();
    const { rerender } = render(
      <RowActionButton icon="delete" label="Delete provider" onClick={onClick} />,
    );

    await user.click(screen.getByRole("button", { name: "Delete provider" }));
    expect(onClick).toHaveBeenCalledTimes(1);

    rerender(
      <RowActionButton icon="delete" label="Delete provider" onClick={onClick} disabled />,
    );
    const disabledButton = screen.getByRole("button", { name: "Delete provider" });
    expect(disabledButton).toBeDisabled();
    await user.click(disabledButton);
    expect(onClick).toHaveBeenCalledTimes(1);
  });
});

describe("RowActionLink", () => {
  it("renders a link action that navigates through the consumer-supplied link", async () => {
    const user = userEvent.setup();
    renderRoutes(
      <RowActions>
        <RowActionLink icon="edit" label="Edit workflow" tooltip="Opens the editor">
          <Link to="/workflows/wf-1/edit" />
        </RowActionLink>
      </RowActions>,
    );

    const group = screen.getByRole("group");
    const link = within(group).getByRole("link", { name: "Edit workflow" });
    expect(link).toHaveAttribute("href", "/workflows/wf-1/edit");
    // The link is the single interactive element: the tooltip trigger is the
    // link itself, with no nested button inside.
    expect(within(group).getAllByRole("link")).toHaveLength(1);
    expect(within(group).queryAllByRole("button")).toHaveLength(0);

    await user.click(link);
    expect(screen.getByTestId("location")).toHaveTextContent("/workflows/wf-1/edit");
  });

  it("suppresses navigation of a disabled link action", async () => {
    const user = userEvent.setup();
    renderRoutes(
      <RowActionLink icon="edit" label="Edit workflow" disabled>
        <Link to="/workflows/wf-1/edit" />
      </RowActionLink>,
    );

    const link = screen.getByRole("link", { name: "Edit workflow" });
    expect(link).toHaveAttribute("aria-disabled", "true");
    await user.click(link);
    expect(screen.getByTestId("location")).toHaveTextContent("/workflows");
  });
});

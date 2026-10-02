import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { Button } from "./button";
import { Icon } from "./icon";
import { Tooltip, TooltipContent, TooltipTrigger } from "./tooltip";

// jsdom does not implement ResizeObserver, which Radix popper-based content
// measures with. Same no-op stub convention as Canvas.test.tsx.
class ResizeObserverStub {
  observe() {}
  unobserve() {}
  disconnect() {}
}
vi.stubGlobal("ResizeObserver", ResizeObserverStub);

// Mirrors the intended RowActions wiring (AC-08): an icon-only trigger keeps
// its own accessible name via aria-label; the tooltip is a hint, never the
// name. The trigger supplies the accessible name, not the tooltip.
function Host() {
  return (
    <Tooltip>
      <TooltipTrigger asChild>
        <Button variant="ghost" size="icon-sm" aria-label="Edit configuration">
          <Icon name="edit" />
        </Button>
      </TooltipTrigger>
      <TooltipContent>Edit configuration</TooltipContent>
    </Tooltip>
  );
}

describe("Tooltip", () => {
  it("opens on keyboard focus and links itself through aria-describedby", async () => {
    const user = userEvent.setup();
    render(<Host />);

    expect(screen.queryByRole("tooltip")).not.toBeInTheDocument();

    await user.tab();

    const tooltip = await screen.findByRole("tooltip");
    expect(tooltip).toHaveTextContent("Edit configuration");

    const trigger = screen.getByRole("button", { name: "Edit configuration" });
    expect(trigger).toHaveAttribute("aria-describedby", tooltip.id);
    // The tooltip must not become the trigger's accessible name.
    expect(trigger).toHaveAccessibleName("Edit configuration");
  });

  it("opens on hover after the short delay", async () => {
    const user = userEvent.setup();
    render(<Host />);

    await user.hover(screen.getByRole("button", { name: "Edit configuration" }));

    const tooltip = await screen.findByRole("tooltip");
    expect(tooltip).toHaveTextContent("Edit configuration");
  });
});

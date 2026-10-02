import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useState } from "react";
import { describe, expect, it, vi } from "vitest";

import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "./dropdown-menu";

// jsdom does not implement ResizeObserver, which Radix popper-based content
// measures with. Same no-op stub convention as Canvas.test.tsx.
class ResizeObserverStub {
  observe() {}
  unobserve() {}
  disconnect() {}
}
vi.stubGlobal("ResizeObserver", ResizeObserverStub);

// Controlled host mirroring the planned avatar-menu wiring (AC-05): the owner
// keeps the open state; the menu only reports intent through onOpenChange.
function Host({ onSelect }: { onSelect?: () => void }) {
  const [open, setOpen] = useState(false);
  return (
    <DropdownMenu open={open} onOpenChange={setOpen}>
      <DropdownMenuTrigger>Account</DropdownMenuTrigger>
      <DropdownMenuContent>
        <DropdownMenuItem onSelect={onSelect}>Sign out</DropdownMenuItem>
      </DropdownMenuContent>
    </DropdownMenu>
  );
}

describe("DropdownMenu", () => {
  it("opens on trigger click, exposes the menu ARIA state, and renders the item as a menuitem", async () => {
    const user = userEvent.setup();
    render(<Host />);

    const trigger = screen.getByRole("button", { name: "Account" });
    expect(trigger).toHaveAttribute("aria-haspopup", "menu");
    expect(trigger).toHaveAttribute("aria-expanded", "false");

    await user.click(trigger);

    expect(trigger).toHaveAttribute("aria-expanded", "true");
    // role="menuitem" also opts the item into the base-layer pointer-cursor
    // rule (AC-04).
    expect(screen.getByRole("menuitem", { name: "Sign out" })).toBeInTheDocument();
  });

  it("is keyboard reachable: ArrowDown highlights the item and Enter activates it", async () => {
    const user = userEvent.setup();
    const onSelect = vi.fn();
    render(<Host onSelect={onSelect} />);

    await user.click(screen.getByRole("button", { name: "Account" }));
    await user.keyboard("{ArrowDown}");

    const item = screen.getByRole("menuitem", { name: "Sign out" });
    expect(item).toHaveAttribute("data-highlighted");

    await user.keyboard("{Enter}");
    expect(onSelect).toHaveBeenCalledTimes(1);
  });

  it("closes on Escape", async () => {
    const user = userEvent.setup();
    render(<Host />);

    await user.click(screen.getByRole("button", { name: "Account" }));
    expect(screen.getByRole("menuitem", { name: "Sign out" })).toBeInTheDocument();

    await user.keyboard("{Escape}");

    expect(screen.queryByRole("menuitem", { name: "Sign out" })).not.toBeInTheDocument();
  });
});

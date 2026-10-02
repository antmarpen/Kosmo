import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useState, type ReactNode } from "react";
import { describe, expect, it, vi } from "vitest";

import { ICON_NAMES } from "./icon-names";
import { Dialog, DialogContent, DialogTitle } from "./dialog";

/**
 * Controlled host mirroring real usage: Radix portals the content, so the
 * open state must live in a component. Every modal in the app composes
 * `DialogContent` with a `DialogTitle`, so the host does too.
 */
function Host({
  showClose,
  closeDisabled,
  closeLabel,
  onOpenChange,
  children,
}: {
  showClose?: boolean;
  closeDisabled?: boolean;
  closeLabel?: string;
  onOpenChange?: (open: boolean) => void;
  children?: ReactNode;
}) {
  const [open, setOpen] = useState(true);
  return (
    <Dialog
      open={open}
      onOpenChange={(next) => {
        onOpenChange?.(next);
        setOpen(next);
      }}
    >
      <DialogContent
        showClose={showClose}
        closeDisabled={closeDisabled}
        closeLabel={closeLabel}
      >
        <DialogTitle>Create a workflow</DialogTitle>
        {children}
      </DialogContent>
    </Dialog>
  );
}

describe("DialogContent close X", () => {
  it("renders a top-right close X by default, named from the shared common.close key", () => {
    render(<Host><p>Dialog body</p></Host>);

    const close = screen.getByRole("button", { name: "Close" });
    // The X lives inside the dialog and carries the shared decorative icon.
    expect(close.closest('[data-slot="dialog-content"]')).not.toBeNull();
    expect(close).toHaveAttribute("type", "button");
    expect(close).toBeEnabled();
    expect(screen.getByText(ICON_NAMES.close)).toHaveAttribute("aria-hidden", "true");
    expect(screen.getByText("Dialog body")).toBeInTheDocument();
  });

  it("gives the X initial focus: rendered before children, it is the first tabbable element (the safe action)", async () => {
    render(<Host><button type="button">Inside dialog</button></Host>);

    await waitFor(() =>
      expect(screen.getByRole("button", { name: "Close" })).toHaveFocus(),
    );
  });

  it("closes the dialog when the X is clicked and reports the close to the owner", async () => {
    const user = userEvent.setup();
    const onOpenChange = vi.fn();
    render(<Host onOpenChange={onOpenChange}><p>Dialog body</p></Host>);

    await user.click(screen.getByRole("button", { name: "Close" }));

    expect(onOpenChange).toHaveBeenCalledWith(false);
    await waitFor(() =>
      expect(screen.queryByRole("dialog")).not.toBeInTheDocument(),
    );
  });

  it("showClose={false} renders no close control", () => {
    render(<Host showClose={false}><p>Dialog body</p></Host>);

    expect(screen.queryByRole("button", { name: "Close" })).not.toBeInTheDocument();
    expect(screen.getByRole("dialog")).toBeInTheDocument();
  });

  it("closeDisabled disables the X so in-flight work cannot be dismissed", async () => {
    const user = userEvent.setup();
    const onOpenChange = vi.fn();
    render(<Host closeDisabled onOpenChange={onOpenChange}><p>Dialog body</p></Host>);

    const close = screen.getByRole("button", { name: "Close" });
    expect(close).toBeDisabled();

    await user.click(close);
    expect(onOpenChange).not.toHaveBeenCalled();
    expect(screen.getByRole("dialog")).toBeInTheDocument();
  });

  it("closeLabel overrides the accessible name", () => {
    render(<Host closeLabel="Dismiss"><p>Dialog body</p></Host>);

    expect(screen.getByRole("button", { name: "Dismiss" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Close" })).not.toBeInTheDocument();
  });

  it("never submits an enclosing form (type=button)", () => {
    render(<Host><form><p>Form inside the modal</p></form></Host>);

    expect(screen.getByRole("button", { name: "Close" })).toHaveAttribute(
      "type",
      "button",
    );
  });
});

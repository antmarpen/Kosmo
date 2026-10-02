import { render, screen, waitFor } from "@testing-library/react";
import userEvent, { PointerEventsCheckLevel } from "@testing-library/user-event";
import { useState } from "react";
import { describe, expect, it, vi } from "vitest";

import { ConfirmDialog, type ConfirmDialogProps } from "./ConfirmDialog";

// All user-facing strings arrive as props (the consuming feature passes
// localized catalog values); the test mirrors that contract with literals.
// The close affordance is the shared `DialogContent` X, named by the
// localized `common.close` catalog value ("Close").
function baseProps(overrides: Partial<ConfirmDialogProps> = {}): ConfirmDialogProps {
  return {
    open: true,
    onOpenChange: () => undefined,
    title: "Delete provider",
    description: "This permanently removes the stored credentials.",
    confirmLabel: "Delete",
    onConfirm: () => undefined,
    ...overrides,
  };
}

function renderConfirmDialog(props: Partial<ConfirmDialogProps> = {}) {
  const onOpenChange = vi.fn();
  const onConfirm = vi.fn();
  const propsWithMocks = baseProps({ onOpenChange, onConfirm, ...props });
  const view = render(<ConfirmDialog {...propsWithMocks} />);
  const rerenderWith = (next: Partial<ConfirmDialogProps>) =>
    view.rerender(<ConfirmDialog {...baseProps({ ...propsWithMocks, ...next })} />);
  return { onOpenChange, onConfirm, rerenderWith, ...view };
}

// Stateful host mirroring real usage: a parent trigger owns the open state so
// Radix can restore focus to the previously focused element on close.
function Host({
  loading = false,
  onConfirm = () => undefined,
}: {
  loading?: boolean;
  onConfirm?: () => void;
}) {
  const [open, setOpen] = useState(false);
  return (
    <>
      <button type="button" onClick={() => setOpen(true)}>
        Stop task
      </button>
      <ConfirmDialog
        open={open}
        onOpenChange={setOpen}
        title="Stop task"
        description="The running task will be stopped."
        confirmLabel="Stop"
        onConfirm={onConfirm}
        loading={loading}
      />
    </>
  );
}

describe("ConfirmDialog", () => {
  it("renders the title, description, the confirm action, and the shared close X as an alert dialog", () => {
    renderConfirmDialog();

    const dialog = screen.getByRole("alertdialog", { name: "Delete provider" });
    expect(dialog).toHaveTextContent("This permanently removes the stored credentials.");
    expect(screen.getByRole("button", { name: "Delete" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Close" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Cancel" })).not.toBeInTheDocument();
  });

  it("renders nothing when closed", () => {
    renderConfirmDialog({ open: false });

    expect(screen.queryByRole("alertdialog")).not.toBeInTheDocument();
  });

  it("puts initial focus on the shared close X (the safe action)", async () => {
    renderConfirmDialog();

    await waitFor(() =>
      expect(screen.getByRole("button", { name: "Close" })).toHaveFocus(),
    );
  });

  it("confirm calls onConfirm; the parent owns closing, so the dialog stays open", async () => {
    const user = userEvent.setup();
    const { onConfirm, onOpenChange } = renderConfirmDialog();

    await user.click(screen.getByRole("button", { name: "Delete" }));

    expect(onConfirm).toHaveBeenCalledTimes(1);
    expect(onOpenChange).not.toHaveBeenCalled();
    expect(screen.getByRole("alertdialog", { name: "Delete provider" })).toBeInTheDocument();
  });

  it("the close X dismisses without confirming and reports onOpenChange(false)", async () => {
    const user = userEvent.setup();
    const { onOpenChange, onConfirm } = renderConfirmDialog();

    await user.click(screen.getByRole("button", { name: "Close" }));

    expect(onOpenChange).toHaveBeenCalledWith(false);
    expect(onConfirm).not.toHaveBeenCalled();
  });

  it("Escape cancels and restores focus to the previously focused element", async () => {
    const user = userEvent.setup();
    render(<Host />);

    const opener = screen.getByRole("button", { name: "Stop task" });
    await user.click(opener);
    await waitFor(() =>
      expect(screen.getByRole("button", { name: "Close" })).toHaveFocus(),
    );

    await user.keyboard("{Escape}");

    await waitFor(() => {
      expect(screen.queryByRole("alertdialog")).not.toBeInTheDocument();
      expect(opener).toHaveFocus();
    });
  });

  it("while loading, duplicate confirm is suppressed and dismissal is prevented", async () => {
    // The modal dialog locks `body` to `pointer-events: none` (Radix modal
    // behavior; in a real browser a pointerdown still lands outside). The
    // user-event pointer-events guardrail has no hit-testing to consult in
    // jsdom, so it is disabled for this interaction only; the full
    // pointerdown -> click sequence is still simulated.
    const user = userEvent.setup({ pointerEventsCheck: PointerEventsCheckLevel.Never });
    const { onConfirm, onOpenChange, rerenderWith } = renderConfirmDialog();

    // The first click starts the in-flight action; the parent would flip
    // loading on while the mutation runs.
    await user.click(screen.getByRole("button", { name: "Delete" }));
    expect(onConfirm).toHaveBeenCalledTimes(1);

    rerenderWith({ loading: true });

    const confirm = screen.getByRole("button", { name: "Delete" });
    expect(confirm).toBeDisabled();
    expect(confirm).toHaveAttribute("aria-busy", "true");
    expect(screen.getByRole("button", { name: "Close" })).toBeDisabled();

    await user.click(confirm);
    expect(onConfirm).toHaveBeenCalledTimes(1);

    await user.keyboard("{Escape}");
    expect(onOpenChange).not.toHaveBeenCalledWith(false);

    await user.click(document.body);
    expect(onOpenChange).not.toHaveBeenCalledWith(false);

    // The in-flight state stays visible; the user is not trapped forever
    // because the parent flips loading back off when the action settles.
    expect(screen.getByRole("alertdialog", { name: "Delete provider" })).toBeInTheDocument();
  });

  it("after loading ends, closing and retry work again", async () => {
    const user = userEvent.setup();
    const { onConfirm, onOpenChange, rerenderWith } = renderConfirmDialog({ loading: true });

    rerenderWith({ loading: false });

    const confirm = screen.getByRole("button", { name: "Delete" });
    expect(confirm).toBeEnabled();
    await user.click(confirm);
    expect(onConfirm).toHaveBeenCalledTimes(1);

    await user.click(screen.getByRole("button", { name: "Close" }));
    expect(onOpenChange).toHaveBeenCalledWith(false);
  });

  it("defaults the confirm action to destructive styling and can opt out", () => {
    const { unmount } = renderConfirmDialog();

    expect(screen.getByRole("button", { name: "Delete" })).toHaveAttribute(
      "data-variant",
      "destructive",
    );
    unmount();

    renderConfirmDialog({ destructive: false });
    expect(screen.getByRole("button", { name: "Delete" })).toHaveAttribute(
      "data-variant",
      "default",
    );
  });
});

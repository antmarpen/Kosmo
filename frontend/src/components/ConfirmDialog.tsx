import * as React from "react";

import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";

export type ConfirmDialogProps = {
  /** Controlled open state; the parent owns closing after the action settles. */
  open: boolean;
  onOpenChange: (open: boolean) => void;
  title: string;
  description: string;
  confirmLabel: string;
  /** Started by the confirm button; the dialog only reports intent. */
  onConfirm: () => void;
  /**
   * While the confirmed action is in flight: the confirm button is disabled
   * with an inline spinner, the shared close X is disabled, and
   * Escape/outside dismissal is prevented so the result of the action
   * cannot be orphaned mid-mutation.
   */
  loading?: boolean;
  /** Destructive styling for the confirm action. Default true. */
  destructive?: boolean;
};

/**
 * Styled confirmation dialog for destructive and mutating actions (AC-16),
 * replacing `window.confirm`. All user-facing text arrives through props so
 * consuming features pass localized catalog values; the close affordance is
 * the shared `DialogContent` X (localized `common.close`).
 *
 * Focus contract: initial focus lands on the shared close X — the safe
 * action, rendered first by `DialogContent` — never on the confirm button;
 * on close, focus returns to the element focused before the dialog opened.
 * Radix's built-in restore only targets a rendered `DialogTrigger`, which
 * this controlled component does not own, so the capture/restore is
 * implemented here.
 */
function ConfirmDialog({
  open,
  onOpenChange,
  title,
  description,
  confirmLabel,
  onConfirm,
  loading = false,
  destructive = true,
}: ConfirmDialogProps) {
  const lastFocusedRef = React.useRef<HTMLElement | null>(null);

  const handleOpenAutoFocus = () => {
    // Record the opener before Radix moves focus into the dialog; the
    // default first-tabbable behavior (the shared close X) stays untouched.
    lastFocusedRef.current = document.activeElement as HTMLElement | null;
  };

  const handleCloseAutoFocus = (event: Event) => {
    // Radix's modal default restores focus to `DialogTrigger`, which
    // confirm flows do not render; restore the captured opener instead.
    event.preventDefault();
    lastFocusedRef.current?.focus();
    lastFocusedRef.current = null;
  };

  const holdOpenWhileLoading = (event: Event) => {
    if (loading) event.preventDefault();
  };

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent
        role="alertdialog"
        closeDisabled={loading}
        onOpenAutoFocus={handleOpenAutoFocus}
        onCloseAutoFocus={handleCloseAutoFocus}
        onEscapeKeyDown={holdOpenWhileLoading}
        onInteractOutside={holdOpenWhileLoading}
      >
        <DialogHeader>
          <DialogTitle>{title}</DialogTitle>
          <DialogDescription>{description}</DialogDescription>
        </DialogHeader>
        <DialogFooter>
          <Button
            type="button"
            variant={destructive ? "destructive" : "default"}
            loading={loading}
            onClick={onConfirm}
          >
            {confirmLabel}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

export { ConfirmDialog };

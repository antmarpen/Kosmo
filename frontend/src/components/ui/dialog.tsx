import * as React from "react";
import * as DialogPrimitive from "@radix-ui/react-dialog";
import { useTranslation } from "react-i18next";

import { Icon } from "@/components/ui/icon";
import { cn } from "@/lib/utils";

/**
 * Styled Radix dialog primitives (shadcn/ui conventions).
 *
 * Modal by default: focus is trapped inside the content, focus returns to
 * the previously focused element on close, and Escape or an outside
 * pointer-down dismiss through `onOpenChange(false)`. Dismissal callbacks
 * (`onEscapeKeyDown`, `onInteractOutside`) pass through to consumers, which
 * is how `ConfirmDialog` holds the dialog open while an action is in
 * flight.
 *
 * `DialogContent` renders a top-right close "X" by default, so every modal
 * — current and future — shares one close affordance (owner decision that
 * replaces per-dialog footer Cancel buttons):
 *
 * - It is rendered before `children`, making it the first tabbable element
 *   and therefore the initial-focus target (a safe action that dismisses
 *   without confirming). Pass `onOpenAutoFocus` to move initial focus
 *   elsewhere (e.g. a form's primary input).
 * - It is `type="button"`, so it never submits an enclosing `<form>`.
 * - Its accessible name defaults to the localized `common.close` catalog
 *   value — the one piece of user-facing text these primitives own — and
 *   can be overridden with `closeLabel`.
 * - `closeDisabled` disables it while an action is in flight so the result
 *   of a mutation cannot be orphaned; `showClose={false}` opts out.
 * - While the X renders, `DialogHeader` reserves right padding so a long
 *   title never runs underneath it.
 *
 * `DialogClose` stays exported for consumers composing custom close
 * affordances.
 */

function Dialog(props: React.ComponentProps<typeof DialogPrimitive.Root>) {
  return <DialogPrimitive.Root data-slot="dialog" {...props} />;
}

function DialogTrigger(props: React.ComponentProps<typeof DialogPrimitive.Trigger>) {
  return <DialogPrimitive.Trigger data-slot="dialog-trigger" {...props} />;
}

function DialogPortal(props: React.ComponentProps<typeof DialogPrimitive.Portal>) {
  return <DialogPrimitive.Portal data-slot="dialog-portal" {...props} />;
}

function DialogClose(props: React.ComponentProps<typeof DialogPrimitive.Close>) {
  return <DialogPrimitive.Close data-slot="dialog-close" {...props} />;
}

function DialogOverlay({
  className,
  ...props
}: React.ComponentProps<typeof DialogPrimitive.Overlay>) {
  return (
    <DialogPrimitive.Overlay
      data-slot="dialog-overlay"
      className={cn("fixed inset-0 z-50 bg-black/50", className)}
      {...props}
    />
  );
}

type DialogContentProps = React.ComponentProps<typeof DialogPrimitive.Content> & {
  /** Accessible name of the built-in close X. Defaults to `common.close`. */
  closeLabel?: string;
  /**
   * Disables the close X while an action is in flight, so the result of a
   * mutation cannot be dismissed mid-flight. Default false.
   */
  closeDisabled?: boolean;
  /** Renders the built-in top-right close X. Default true. */
  showClose?: boolean;
};

function DialogContent({
  className,
  children,
  closeLabel,
  closeDisabled = false,
  showClose = true,
  ...props
}: DialogContentProps) {
  const { t } = useTranslation();

  return (
    <DialogPortal>
      <DialogOverlay />
      <DialogPrimitive.Content
        data-slot="dialog-content"
        className={cn(
          "fixed top-1/2 left-1/2 z-50 grid w-full max-w-[calc(100%-2rem)] -translate-x-1/2 -translate-y-1/2 gap-4 rounded-xl border bg-background p-6 shadow-sm sm:max-w-lg",
          // Reserve header space beside the X so a long title never runs
          // underneath it; content outside the header keeps its padding.
          showClose && "[&>[data-slot=dialog-header]]:pr-14",
          className
        )}
        {...props}
      >
        {showClose && (
          <DialogClose
            type="button"
            aria-label={closeLabel ?? t("common.close")}
            disabled={closeDisabled}
            // Ghost icon-button vocabulary from `Button` (`icon-sm`):
            // circular hit target, accent hover, visible focus ring,
            // standard disabled affordance.
            className={cn(
              "absolute top-4 right-4 inline-flex size-8 shrink-0 items-center justify-center rounded-full text-sm font-medium whitespace-nowrap transition-all outline-none",
              "hover:bg-accent hover:text-accent-foreground dark:hover:bg-accent/50",
              "focus-visible:border-ring focus-visible:ring-[3px] focus-visible:ring-ring/50",
              "disabled:cursor-not-allowed disabled:opacity-50"
            )}
          >
            <Icon name="close" size={16} aria-hidden="true" />
          </DialogClose>
        )}
        {children}
      </DialogPrimitive.Content>
    </DialogPortal>
  );
}

function DialogHeader({ className, ...props }: React.ComponentProps<"div">) {
  return (
    <div
      data-slot="dialog-header"
      className={cn("flex flex-col gap-2 text-center sm:text-left", className)}
      {...props}
    />
  );
}

function DialogFooter({ className, ...props }: React.ComponentProps<"div">) {
  return (
    <div
      data-slot="dialog-footer"
      className={cn("flex flex-col-reverse gap-2 sm:flex-row sm:justify-end", className)}
      {...props}
    />
  );
}

function DialogTitle({
  className,
  ...props
}: React.ComponentProps<typeof DialogPrimitive.Title>) {
  return (
    <DialogPrimitive.Title
      data-slot="dialog-title"
      className={cn("text-lg leading-none font-semibold", className)}
      {...props}
    />
  );
}

function DialogDescription({
  className,
  ...props
}: React.ComponentProps<typeof DialogPrimitive.Description>) {
  return (
    <DialogPrimitive.Description
      data-slot="dialog-description"
      className={cn("text-sm text-muted-foreground", className)}
      {...props}
    />
  );
}

export {
  Dialog,
  DialogPortal,
  DialogOverlay,
  DialogTrigger,
  DialogClose,
  DialogContent,
  DialogHeader,
  DialogFooter,
  DialogTitle,
  DialogDescription,
};

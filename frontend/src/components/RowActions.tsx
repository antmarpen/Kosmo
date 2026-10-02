import * as React from "react";

import { Button } from "@/components/ui/button";
import { Icon, type MaterialIconName } from "@/components/ui/icon";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import { cn } from "@/lib/utils";

/**
 * Shared per-row actions presentation (spec AC-08 / D7): a right-aligned
 * group of compact icon actions placed at the end of list rows.
 *
 * The group accepts explicitly supplied children — one per action — and is
 * deliberately not an action registry: each list owns and declares its own
 * actions inline. Place it as the trailing child of the row; `ml-auto` keeps
 * it on the trailing edge in flex rows at every breakpoint.
 */
export type RowActionsProps = React.ComponentProps<"div">;

function RowActions({ className, ...props }: RowActionsProps) {
  return (
    <div
      role="group"
      data-slot="row-actions"
      className={cn("ml-auto flex shrink-0 items-center justify-end gap-1", className)}
      {...props}
    />
  );
}

/**
 * Common contract of row actions: all user-facing text arrives as props so
 * consuming features pass localized catalog values (same contract as
 * `ConfirmDialog`). `variant` and `size` are intentionally fixed to keep one
 * shared presentation (ghost, 36px touch target) across every list.
 */
type RowActionProps = Omit<
  React.ComponentProps<typeof Button>,
  "asChild" | "children" | "aria-label" | "variant" | "size"
> & {
  /** Semantic icon name from the shared `ICON_NAMES` registry. */
  icon: MaterialIconName;
  /**
   * Accessible name of the action (localized). The tooltip supplements this
   * name and never replaces it.
   */
  label: string;
  /** Tooltip text; defaults to `label` when omitted. */
  tooltip?: string;
};

/**
 * Compact icon-only action button for list rows. Composes the shared
 * `Button` (ghost, `size="icon"` — a 36px touch target) with a decorative
 * `Icon` and a `Tooltip` whose trigger is the button itself, so there are no
 * nested interactive elements. Pass `disabled` (or `loading`) to make the
 * action non-activatable; the accessible name always comes from `label`.
 */
function RowActionButton({ icon, label, tooltip, className, ...buttonProps }: RowActionProps) {
  return (
    <Tooltip>
      <TooltipTrigger asChild>
        <Button
          type="button"
          variant="ghost"
          size="icon"
          className={className}
          {...buttonProps}
          aria-label={label}
        >
          <Icon name={icon} />
        </Button>
      </TooltipTrigger>
      <TooltipContent>{tooltip ?? label}</TooltipContent>
    </Tooltip>
  );
}

export type RowActionLinkProps = RowActionProps & {
  /**
   * The anchor or router link rendered as the action trigger — typically an
   * empty `<Link to="..." />`, since the icon and the accessible name come
   * from the `icon` and `label` props. Keep it free of nested interactive
   * elements.
   */
  children: React.ReactElement;
};

/**
 * Row-action presentation for navigation: the same compact icon + tooltip
 * composition as `RowActionButton`, rendered through `Button asChild` so the
 * consumer-supplied link is the single interactive element. A `disabled`
 * action keeps the link presentation with `aria-disabled` and suppresses
 * activation: `Button` prevents the default, and react-router `Link` skips
 * its internal navigation when the click was prevented.
 */
function RowActionLink({
  icon,
  label,
  tooltip,
  children,
  className,
  ...buttonProps
}: RowActionLinkProps) {
  const child = children as React.ReactElement<{ children?: React.ReactNode }>;
  return (
    <Tooltip>
      <TooltipTrigger asChild>
        <Button
          asChild
          variant="ghost"
          size="icon"
          className={className}
          {...buttonProps}
          aria-label={label}
        >
          {React.cloneElement(child, undefined, <Icon name={icon} />, child.props.children)}
        </Button>
      </TooltipTrigger>
      <TooltipContent>{tooltip ?? label}</TooltipContent>
    </Tooltip>
  );
}

export { RowActions, RowActionButton, RowActionLink };

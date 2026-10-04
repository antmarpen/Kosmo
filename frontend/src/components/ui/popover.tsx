import * as React from "react";
import * as Primitive from "@radix-ui/react-popover";
import { cn } from "@/lib/utils";

export const Popover = Primitive.Root;
export const PopoverTrigger = Primitive.Trigger;
/** Non-interactive positioning anchor (combobox triggers that own their state). */
export const PopoverAnchor = Primitive.Anchor;
export function PopoverContent({ className, sideOffset = 6, ...props }: React.ComponentProps<typeof Primitive.Content>) {
  return <Primitive.Portal><Primitive.Content sideOffset={sideOffset} collisionPadding={12} className={cn("z-[60] w-72 max-w-[calc(100vw-1.5rem)] rounded-md border bg-popover p-3 text-popover-foreground shadow-md outline-none", className)} {...props} /></Primitive.Portal>;
}

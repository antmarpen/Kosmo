import { forwardRef } from "react";
import { cn } from "@/lib/utils";

type SwitchProps = Omit<React.ButtonHTMLAttributes<HTMLButtonElement>, "onChange" | "type"> & {
  checked: boolean;
  onCheckedChange: (checked: boolean) => void;
};

export const Switch = forwardRef<HTMLButtonElement, SwitchProps>(function Switch({ checked, onCheckedChange, disabled, className, onClick, onKeyDown, ...props }, ref) {
  const toggle = () => { if (!disabled) onCheckedChange(!checked); };
  return <button {...props} ref={ref} type="button" role="switch" aria-checked={checked} disabled={disabled}
    onClick={(event) => { onClick?.(event); toggle(); }}
    onKeyDown={onKeyDown}
    className={cn("relative inline-flex h-5 w-9 shrink-0 cursor-pointer items-center rounded-full border border-transparent transition-colors focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-ring disabled:cursor-not-allowed disabled:opacity-50", checked ? "bg-primary" : "bg-input", className)}>
    <span aria-hidden="true" className={cn("pointer-events-none block size-4 rounded-full bg-background shadow-sm transition-transform", checked ? "translate-x-4" : "translate-x-0")} />
  </button>;
});

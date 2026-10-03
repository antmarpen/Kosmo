import type { ReactNode } from "react";
import { Icon } from "@/components/ui/icon";

/** Wrap a control to keep slow-request feedback in place, with an announced live label. */
export function LoadingControl({ label, loading, children }: { label: string; loading: boolean; children: ReactNode }) {
  return <div className="relative">
    {children}
    {loading && <span role="status" aria-label={label} className="pointer-events-none absolute inset-y-0 right-3 flex items-center gap-1.5 bg-background pl-2 text-xs text-muted-foreground">
      <Icon name="spinner" className="animate-spin" aria-hidden="true" />{label}
    </span>}
  </div>;
}

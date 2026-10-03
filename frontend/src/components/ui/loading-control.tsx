import type { ReactNode } from "react";
import { Icon } from "@/components/ui/icon";

/** Wrap a control to keep slow-request feedback in place, with an announced live label. */
export function LoadingControl({ label, loading, children }: { label: string; loading: boolean; children: ReactNode }) {
  return <div className="relative">
    {children}
    {loading && <span role="status" aria-label={label} className="pointer-events-none absolute inset-0 z-10 flex items-center justify-center gap-2 rounded-md bg-background px-3 text-xs font-medium text-muted-foreground">
      <Icon name="spinner" className="animate-spin" aria-hidden="true" />{label}
    </span>}
  </div>;
}

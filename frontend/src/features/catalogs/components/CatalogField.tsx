import * as React from "react";

import { cn } from "@/lib/utils";

/**
 * Bounded form-field presentation for the catalog screens (WP-12): a labeled
 * group that wires the label, the hint and the error message onto the control
 * it wraps. This is deliberately a thin wrapper — not a form engine — and it
 * composes any native or shared control (`Input`, `CatalogTextArea`, `select`).
 *
 * Contract: exactly one control child. The child receives a generated id (or
 * keeps its own), `aria-invalid` when an error is present, and an
 * `aria-describedby` list combining its own descriptions with the hint and
 * error. The error renders with `role="alert"` so it is announced.
 */
export type CatalogFieldProps = {
  label: string;
  /** Persistent helper text, announced as the control's description. */
  hint?: string;
  /** Validation error; when present the control is marked `aria-invalid`. */
  error?: string;
  className?: string;
  children: React.ReactElement;
};

export function CatalogField({ label, hint, error, className, children }: CatalogFieldProps) {
  const generatedId = React.useId();
  const hintId = hint ? `${generatedId}-hint` : undefined;
  const errorId = error ? `${generatedId}-error` : undefined;

  const control = React.Children.only(children) as React.ReactElement<{
    id?: string;
    "aria-describedby"?: string;
    "aria-invalid"?: boolean | "true" | "false";
  }>;
  const ownId = control.props.id;
  const describedBy = [
    control.props["aria-describedby"],
    hintId,
    errorId,
  ]
    .filter(Boolean)
    .join(" ") || undefined;

  const wiredControl = React.cloneElement(control, {
    id: ownId ?? `${generatedId}-control`,
    "aria-describedby": describedBy,
    ...(error ? { "aria-invalid": true } : {}),
  });

  return (
    <div data-slot="catalog-field" className={cn("grid min-w-0 gap-1.5", className)}>
      <label htmlFor={ownId ?? `${generatedId}-control`} className="text-sm font-medium">
        {label}
      </label>
      {wiredControl}
      {hint ? (
        <p id={hintId} className="text-xs leading-5 text-muted-foreground">
          {hint}
        </p>
      ) : null}
      {error ? (
        <p id={errorId} role="alert" className="text-xs leading-5 text-destructive">
          {error}
        </p>
      ) : null}
    </div>
  );
}

/**
 * Multiline control styled after the shared `Input` (same border, ring and
 * disabled vocabulary) with a monospace face, for Markdown instruction bodies.
 */
export function CatalogTextArea({
  className,
  rows = 8,
  ...props
}: React.ComponentProps<"textarea">) {
  return (
    <textarea
      data-slot="catalog-textarea"
      rows={rows}
      className={cn(
        "w-full min-w-0 resize-y rounded-lg border border-input bg-transparent px-3 py-2 font-mono text-sm shadow-xs transition-[color,box-shadow] outline-none",
        "focus-visible:border-ring focus-visible:ring-[3px] focus-visible:ring-ring/50",
        "aria-invalid:border-destructive aria-invalid:ring-destructive/20 dark:aria-invalid:ring-destructive/40",
        "disabled:cursor-not-allowed disabled:opacity-50",
        className,
      )}
      {...props}
    />
  );
}

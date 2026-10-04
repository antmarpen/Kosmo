import { createContext, type CSSProperties, type ReactNode, useContext } from "react";
import { useTranslation } from "react-i18next";

import { KosmoErrorAlert, type KosmoError } from "@/components/KosmoErrorAlert";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";

/**
 * Bounded list presentation for the catalog screens (WP-12): the page header,
 * the bordered list container with an optional muted column header, the row
 * shell, and the shared loading / empty / error states. Visual vocabulary
 * mirrors the established provider list; rows end with the shared
 * `RowActions` group supplied by the consuming screen.
 */

/** Page header with title, description and the page-level action (e.g. Add). */
export function CatalogPageHeader({
  title,
  description,
  action,
}: {
  title: string;
  description?: string;
  action?: ReactNode;
}) {
  return (
    <div className="flex flex-col gap-4 sm:flex-row sm:items-end sm:justify-between">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight text-balance">{title}</h1>
        {description ? (
          <p className="mt-1 max-w-2xl text-sm leading-6 text-muted-foreground">{description}</p>
        ) : null}
      </div>
      {action ? <div className="w-full sm:w-auto">{action}</div> : null}
    </div>
  );
}

/**
 * The grid-template shared by the column header and every row. Data columns
 * share the space equally; the trailing auto column holds the row actions.
 * Screens may pass an explicit `template` (e.g. to widen the name column) to
 * `CatalogList`, which every row inherits; individual rows may override it.
 */
export function catalogGridTemplate(columns: number, template?: string): string {
  return template ?? `repeat(${Math.max(columns, 1)}, minmax(0, 1fr)) auto`;
}

function gridStyle(template: string): CSSProperties {
  return { "--catalog-grid": template } as CSSProperties;
}

/** Rows inherit the owning list's template through this context. */
const CatalogGridContext = createContext<string | undefined>(undefined);

/** Larger-screen column layout; rows stack in a single column below `sm`. */
const GRID_COLUMNS_CLASS = "sm:items-center sm:[grid-template-columns:var(--catalog-grid)]";

/**
 * The list container: an optional column header (localized labels, hidden on
 * small screens where rows stack) followed by the row list. Children are the
 * `<CatalogRow>` elements the screen renders.
 */
export function CatalogList({
  columns,
  template,
  className,
  children,
}: {
  /** Column header labels; omit to render a headerless list. */
  columns?: ReactNode[];
  template?: string;
  className?: string;
  children: ReactNode;
}) {
  const resolved = columns ? catalogGridTemplate(columns.length, template) : undefined;
  return (
    <CatalogGridContext value={resolved}>
      <div
        className={cn("overflow-hidden rounded-lg border border-border", className)}
        style={resolved ? gridStyle(resolved) : undefined}
      >
        {columns ? (
          <div
            role="presentation"
            className={cn("hidden gap-4 bg-muted/60 px-4 py-3 text-xs font-medium text-muted-foreground sm:grid", GRID_COLUMNS_CLASS)}
          >
            {columns.map((label, index) => (
              <span key={index} role="columnheader" className="min-w-0 truncate">
                {label}
              </span>
            ))}
            {/* Trailing actions column keeps header and row tracks aligned. */}
            <span role="columnheader" aria-label="" className="min-w-0" />
          </div>
        ) : null}
        <ul className="divide-y divide-border">{children}</ul>
      </div>
    </CatalogGridContext>
  );
}

/**
 * One list row: a responsive grid whose small-screen layout stacks the cells
 * and whose larger layout follows the owning list's column template (or the
 * row's own `template` override). Screens render their cells (name, scope,
 * meta…) and typically end with a `RowActions`.
 */
export function CatalogRow({
  template,
  className,
  children,
}: {
  template?: string;
  className?: string;
  children: ReactNode;
}) {
  const inherited = useContext(CatalogGridContext);
  const resolved = template ?? inherited;
  return (
    <li
      className={cn(
        "grid gap-3 px-4 py-4",
        resolved && GRID_COLUMNS_CLASS,
        className,
      )}
      style={resolved ? gridStyle(resolved) : undefined}
    >
      {children}
    </li>
  );
}

/** Shared polite loading state for the whole list region. */
export function CatalogLoading() {
  const { t } = useTranslation();
  return (
    <p role="status" className="mt-8 text-sm text-muted-foreground">
      {t("catalog.list.loading")}
    </p>
  );
}

/**
 * Empty state that teaches the first action: title, description and the
 * create affordance, all supplied by the consuming screen (entity-specific
 * copy lives in the screen's own namespace).
 */
export function CatalogEmpty({
  title,
  description,
  action,
}: {
  title: string;
  description: string;
  action?: ReactNode;
}) {
  return (
    <div className="mt-8 border-y border-border py-9">
      <h2 className="font-medium">{title}</h2>
      <p className="mt-1 max-w-xl text-sm leading-6 text-muted-foreground">{description}</p>
      {action ? <div className="mt-5">{action}</div> : null}
    </div>
  );
}

/** Shared list error state: the localized `KosmoError` plus an optional retry. */
export function CatalogLoadError({ error, onRetry }: { error: KosmoError; onRetry?: () => void }) {
  const { t } = useTranslation();
  return (
    <div className="mt-6 space-y-3">
      <KosmoErrorAlert error={error} />
      {onRetry ? (
        <div>
          <Button variant="outline" size="sm" onClick={onRetry}>
            {t("catalog.list.retry")}
          </Button>
        </div>
      ) : null}
    </div>
  );
}

import { useId } from "react";
import { useTranslation } from "react-i18next";

import { cn } from "@/lib/utils";

/**
 * Shared scope control for the catalog screens (WP-12): personal / group /
 * global availability with the group picker, following the established
 * provider-wizard interaction (radio list + native select).
 *
 * Policy mirrored from the approved catalog authorization: personal is always
 * available to authenticated users; the group scope is offered only when the
 * actor manages at least one group; the global scope is offered only to
 * administrators. The picker lists **exactly** the managed groups — groups
 * the actor cannot share to are never rendered as options.
 *
 * All user-facing text comes from the shared `catalog.scope.*` namespace;
 * value state stays with the consuming form.
 */
export type CatalogScope = "personal" | "group" | "global";
export type CatalogManagedGroup = { id: string; name: string };

export function CatalogScopeField({
  scope,
  onScopeChange,
  groupId,
  onGroupIdChange,
  managedGroups,
  globalAllowed,
  disabled = false,
  className,
}: {
  scope: CatalogScope;
  onScopeChange: (scope: CatalogScope) => void;
  /** Selected group id for the group scope; `""` when none chosen yet. */
  groupId: string;
  onGroupIdChange: (groupId: string) => void;
  managedGroups: CatalogManagedGroup[];
  globalAllowed: boolean;
  disabled?: boolean;
  className?: string;
}) {
  const { t } = useTranslation();
  const idPrefix = useId();
  const legendId = `${idPrefix}-legend`;
  const groupSelectId = `${idPrefix}-group`;

  const radio = (value: CatalogScope, label: string) => (
    <label
      key={value}
      className="flex min-h-11 items-center gap-3 rounded-md border border-border px-3 py-2"
    >
      <input
        type="radio"
        name={`${idPrefix}-scope`}
        value={value}
        checked={scope === value}
        onChange={() => onScopeChange(value)}
        disabled={disabled}
        className="accent-primary"
      />
      <span className="text-sm">{label}</span>
    </label>
  );

  return (
    <fieldset
      data-slot="catalog-scope-field"
      className={cn("min-w-0", className)}
      disabled={disabled}
    >
      <div role="radiogroup" aria-labelledby={legendId} className="grid gap-2">
        <span id={legendId} className="text-sm font-medium">
          {t("catalog.scope.legend")}
        </span>
        <p className="text-xs leading-5 text-muted-foreground">
          {t("catalog.scope.description")}
        </p>
        <div className="grid gap-2 sm:grid-cols-3">
          {radio("personal", t("catalog.scope.personal"))}
          {managedGroups.length > 0 ? radio("group", t("catalog.scope.group")) : null}
          {globalAllowed ? radio("global", t("catalog.scope.global")) : null}
        </div>
      </div>
      {managedGroups.length > 0 && scope === "group" ? (
        <div className="mt-3">
          <label htmlFor={groupSelectId} className="mb-2 block text-sm font-medium">
            {t("catalog.scope.groupLabel")}
          </label>
          <select
            id={groupSelectId}
            value={groupId}
            onChange={(event) => onGroupIdChange(event.target.value)}
            disabled={disabled}
            className="h-9 w-full rounded-lg border border-input bg-background px-3 text-sm shadow-xs outline-none focus-visible:border-ring focus-visible:ring-[3px] focus-visible:ring-ring/50 disabled:cursor-not-allowed disabled:opacity-50"
          >
            <option value="">{t("catalog.scope.chooseGroup")}</option>
            {managedGroups.map((group) => (
              <option key={group.id} value={group.id}>
                {group.name}
              </option>
            ))}
          </select>
        </div>
      ) : null}
    </fieldset>
  );
}

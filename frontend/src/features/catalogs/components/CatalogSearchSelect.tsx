import * as React from "react";
import { useId, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";

import { Icon } from "@/components/ui/icon";
import { Input } from "@/components/ui/input";
import { Popover, PopoverAnchor, PopoverContent } from "@/components/ui/popover";
import { cn } from "@/lib/utils";

/**
 * Accessible searchable selection for the catalog screens (WP-12), covering
 * single (one entry) and multi (ordered list of entries) modes behind one
 * interaction model.
 *
 * Pattern: an ARIA combobox. The trigger is the search input itself
 * (`role="combobox"` with `aria-expanded`/`aria-controls`/
 * `aria-activedescendant`); the filtered list renders `role="listbox"` in a
 * portal anchored to the input, so it escapes overflow clipping inside forms
 * and dialogs. Focus stays on the input the whole time (the classic
 * `aria-activedescendant` flow).
 *
 * Keyboard: ArrowUp/ArrowDown move (and open), Home/End jump, Enter chooses,
 * Escape closes. Closing resets the search; reopening a single select
 * prefills the committed selection's name. Enter on a closed input is left
 * untouched so enclosing forms keep submitting.
 *
 * Multi mode keeps the authored order: newly chosen entries append, chips
 * render in value order, and each chip carries its own remove button. Values
 * missing from `options` (stale references) render as "Unavailable" chips
 * with their id, and stay removable — display never silently drops them.
 */
export type CatalogSelectOption = {
  id: string;
  name: string;
  description?: string;
};

type CatalogSearchSelectBase = {
  options: CatalogSelectOption[];
  disabled?: boolean;
  /** Accessible name of the control; localized by the consuming screen. */
  "aria-label"?: string;
  id?: string;
  className?: string;
};

export type CatalogSingleSelectProps = CatalogSearchSelectBase & {
  mode?: "single";
  value: string | null;
  onChange: (value: string | null) => void;
  /** Trigger text shown when nothing is selected. */
  placeholder?: string;
  /** Offers a clear-selection button when a value is set. Default false. */
  clearable?: boolean;
};

export type CatalogMultiSelectProps = CatalogSearchSelectBase & {
  mode: "multi";
  /** Ordered, unique values; unknown ids render as unavailable chips. */
  value: string[];
  onChange: (value: string[]) => void;
};

export type CatalogSearchSelectProps =
  | CatalogSingleSelectProps
  | CatalogMultiSelectProps;

function filterOptions(options: CatalogSelectOption[], query: string): CatalogSelectOption[] {
  const needle = query.trim().toLowerCase();
  if (needle === "") return options;
  return options.filter(
    (option) =>
      option.name.toLowerCase().includes(needle) ||
      (option.description ?? "").toLowerCase().includes(needle),
  );
}

type CoreProps = {
  mode: "single" | "multi";
  /** Ordered selection; single mode holds at most one id. */
  selection: string[];
  setSelection: (next: string[]) => void;
  options: CatalogSelectOption[];
  disabled: boolean;
  clearable: boolean;
  placeholder?: string;
  ariaLabel?: string;
  id?: string;
  className?: string;
};

function SearchSelectCore({
  mode,
  selection,
  setSelection,
  options,
  disabled,
  clearable,
  placeholder,
  ariaLabel,
  id,
  className,
}: CoreProps) {
  const { t } = useTranslation();
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState("");
  const [activeIndex, setActiveIndex] = useState(-1);
  const baseId = useId();
  const listboxId = `${baseId}-listbox`;
  const optionId = (index: number) => `${listboxId}-option-${index}`;

  const optionById = useMemo(
    () => new Map(options.map((option) => [option.id, option])),
    [options],
  );
  const filtered = useMemo(() => filterOptions(options, query), [options, query]);

  const selectedId = mode === "single" ? selection[0] ?? null : null;
  const selectedOption = selectedId !== null ? optionById.get(selectedId) : undefined;

  /** Closed inputs show the committed selection; open inputs show the query. */
  const displayValue = open ? query : selectedOption?.name ?? "";

  function handleOpenChange(next: boolean) {
    setOpen(next);
    if (!next) {
      setQuery("");
      setActiveIndex(-1);
    }
  }

  function openListbox(resetQuery: boolean) {
    if (disabled || open) return;
    const nextQuery = resetQuery && mode === "single" ? selectedOption?.name ?? "" : query;
    const nextFiltered = filterOptions(options, nextQuery);
    const preferred =
      mode === "single" && selectedId !== null
        ? nextFiltered.findIndex((option) => option.id === selectedId)
        : -1;
    setOpen(true);
    if (resetQuery) setQuery(nextQuery);
    setActiveIndex(nextFiltered.length > 0 ? Math.max(preferred, 0) : -1);
  }

  function choose(option: CatalogSelectOption) {
    if (mode === "single") {
      setSelection([option.id]);
      handleOpenChange(false);
      return;
    }
    setSelection(
      selection.includes(option.id)
        ? selection.filter((entry) => entry !== option.id)
        : [...selection, option.id],
    );
  }

  function handleKeyDown(event: React.KeyboardEvent<HTMLInputElement>) {
    if (event.key === "ArrowDown" || event.key === "ArrowUp") {
      event.preventDefault();
      if (!open) {
        openListbox(true);
        return;
      }
      if (filtered.length === 0) return;
      const delta = event.key === "ArrowDown" ? 1 : -1;
      setActiveIndex((current) => {
        if (current < 0) return delta === 1 ? 0 : filtered.length - 1;
        return (current + delta + filtered.length) % filtered.length;
      });
      return;
    }
    if (event.key === "Home" || event.key === "End") {
      if (!open || filtered.length === 0) return;
      event.preventDefault();
      setActiveIndex(event.key === "Home" ? 0 : filtered.length - 1);
      return;
    }
    if (event.key === "Enter") {
      if (!open) return; // Closed inputs keep native form submission.
      const active = activeIndex >= 0 ? filtered[activeIndex] : undefined;
      if (active) {
        event.preventDefault();
        choose(active);
      }
      return;
    }
    if (event.key === "Escape" && open) {
      event.preventDefault();
      handleOpenChange(false);
    }
  }

  const showClear = mode === "single" && clearable && !disabled && selection.length > 0;
  const chips = mode === "multi" ? selection : [];
  // Single-select listbox semantics (ARIA 1.2 combobox pattern): exactly one
  // option carries `aria-selected` — the committed selection, or the active
  // option when nothing is committed. Multi-select marks real selections.
  const markedId =
    mode === "single"
      ? selectedId ??
        (activeIndex >= 0 ? filtered[activeIndex]?.id ?? null : null)
      : null;

  return (
    <Popover open={open} onOpenChange={handleOpenChange}>
      <PopoverAnchor asChild>
        <div className={cn("relative min-w-0", className)}>
          {chips.length > 0 ? (
            <ul className="mb-1.5 flex flex-wrap gap-1.5" aria-label={ariaLabel}>
              {chips.map((chipId) => {
                const option = optionById.get(chipId);
                const chipName = option?.name ?? `${chipId} · ${t("catalog.selection.unavailable")}`;
                return (
                  <li
                    key={chipId}
                    title={option ? undefined : chipId}
                    className="inline-flex min-w-0 max-w-full items-center gap-1 rounded-full border border-border bg-muted/50 py-0.5 pr-1 pl-2.5 text-xs"
                  >
                    <span className="min-w-0 truncate">{chipName}</span>
                    <button
                      type="button"
                      aria-label={t("catalog.selection.remove", { name: chipName })}
                      disabled={disabled}
                      onClick={() => setSelection(selection.filter((entry) => entry !== chipId))}
                      className="inline-flex size-5 shrink-0 items-center justify-center rounded-full outline-none hover:bg-accent focus-visible:ring-[3px] focus-visible:ring-ring/50 disabled:cursor-not-allowed disabled:opacity-50"
                    >
                      <Icon name="close" size={12} aria-hidden="true" />
                    </button>
                  </li>
                );
              })}
            </ul>
          ) : null}
          <div className="relative">
            <Icon
              name="search"
              size={16}
              aria-hidden="true"
              className="pointer-events-none absolute top-1/2 left-3 -translate-y-1/2 text-muted-foreground"
            />
            <Input
              {...(id ? { id } : {})}
              type="text"
              role="combobox"
              autoComplete="off"
              value={displayValue}
              placeholder={placeholder ?? t("catalog.selection.searchPlaceholder")}
              aria-label={ariaLabel}
              aria-expanded={open}
              aria-controls={open ? listboxId : undefined}
              aria-autocomplete="list"
              aria-activedescendant={open && activeIndex >= 0 ? optionId(activeIndex) : undefined}
              aria-disabled={disabled || undefined}
              disabled={disabled}
              onChange={(event) => {
                setQuery(event.target.value);
                openListbox(false);
              }}
              onFocus={() => openListbox(true)}
              onClick={() => openListbox(true)}
              onKeyDown={handleKeyDown}
              className="pr-9 pl-9"
            />
            {showClear ? (
              <button
                type="button"
                aria-label={t("catalog.selection.clear")}
                onMouseDown={(event) => event.preventDefault()}
                onClick={() => setSelection([])}
                className="absolute top-1/2 right-2 inline-flex size-6 -translate-y-1/2 items-center justify-center rounded-full text-muted-foreground outline-none hover:bg-accent hover:text-accent-foreground focus-visible:ring-[3px] focus-visible:ring-ring/50"
              >
                <Icon name="close" size={14} aria-hidden="true" />
              </button>
            ) : null}
          </div>
        </div>
      </PopoverAnchor>
      <PopoverContent
        // Keep focus on the combobox input; the list is pointed at through
        // `aria-activedescendant` instead of moving DOM focus.
        onOpenAutoFocus={(event) => event.preventDefault()}
        className="p-0"
        style={{ width: "var(--radix-popover-anchor-width)", minWidth: "12rem" }}
      >
        <div role="listbox" id={listboxId} aria-label={ariaLabel} className="max-h-64 overflow-y-auto p-1">
          {filtered.map((option, index) => {
            const isSelected = selection.includes(option.id);
            const isActive = index === activeIndex;
            return (
              <div
                key={option.id}
                id={optionId(index)}
                role="option"
                aria-selected={mode === "single" ? option.id === markedId : isSelected}
                onClick={() => choose(option)}
                onMouseMove={() => setActiveIndex(index)}
                className={cn(
                  "flex cursor-pointer items-start gap-2 rounded-md px-2 py-1.5 text-sm",
                  isActive && "bg-accent text-accent-foreground",
                )}
              >
                <span className="min-w-0 flex-1">
                  <span className="block truncate">{option.name}</span>
                  {option.description ? (
                    <span className="block truncate text-xs text-muted-foreground">
                      {option.description}
                    </span>
                  ) : null}
                </span>
                {isSelected ? (
                  <Icon name="check" size={16} aria-hidden="true" className="mt-0.5 shrink-0 text-primary" />
                ) : null}
              </div>
            );
          })}
          {filtered.length === 0 ? (
            <div className="px-2 py-1.5 text-sm text-muted-foreground">
              {t("catalog.selection.noResults", { query })}
            </div>
          ) : null}
        </div>
      </PopoverContent>
    </Popover>
  );
}

/** Shared searchable single/multi selection (see the type docs for modes). */
export function CatalogSearchSelect(props: CatalogSearchSelectProps) {
  const { options, disabled = false, "aria-label": ariaLabel, id, className } = props;
  if (props.mode === "multi") {
    return (
      <SearchSelectCore
        mode="multi"
        selection={props.value}
        setSelection={props.onChange}
        options={options}
        disabled={disabled}
        clearable={false}
        ariaLabel={ariaLabel}
        id={id}
        className={className}
      />
    );
  }
  const { placeholder, clearable = false } = props;
  return (
    <SearchSelectCore
      mode="single"
      selection={props.value !== null ? [props.value] : []}
      setSelection={(next) => props.onChange(next[0] ?? null)}
      options={options}
      disabled={disabled}
      clearable={clearable}
      placeholder={placeholder}
      ariaLabel={ariaLabel}
      id={id}
      className={className}
    />
  );
}

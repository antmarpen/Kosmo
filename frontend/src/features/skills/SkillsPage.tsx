import { type FormEvent, useCallback, useEffect, useId, useRef, useState } from "react";
import { useTranslation } from "react-i18next";

import { toKosmoError } from "@/api/apiError";
import { MarkdownPreview } from "@/components/MarkdownPreview";
import { ConfirmDialog } from "@/components/ConfirmDialog";
import { KosmoErrorAlert, type KosmoError } from "@/components/KosmoErrorAlert";
import { RowActions, RowActionButton } from "@/components/RowActions";
import { Button } from "@/components/ui/button";
import { Icon } from "@/components/ui/icon";
import { Input } from "@/components/ui/input";
import { CatalogField, CatalogTextArea } from "@/features/catalogs/components/CatalogField";
import { useCatalogFormFocus } from "@/features/catalogs/components/useCatalogFormFocus";
import {
  CatalogEmpty,
  CatalogList,
  CatalogLoadError,
  CatalogLoading,
  CatalogPageHeader,
  CatalogRow,
} from "@/features/catalogs/components/CatalogList";
import {
  CatalogScopeField,
  type CatalogManagedGroup,
  type CatalogScope,
} from "@/features/catalogs/components/CatalogScopeField";
import {
  createSkill,
  deleteSkill,
  fetchSkill,
  fetchSkills,
  updateSkill,
} from "@/features/catalogs/api";
import type { SkillCatalogEntry } from "@/features/catalogs/catalogTypes";
import { useCurrentUser } from "@/features/auth/useCurrentUser";
import { cn } from "@/lib/utils";

/**
 * WP-13 — Skill catalog screen (`/admin/skills`): scoped list, create, edit
 * and delete with a Markdown instructions editor and safe preview.
 *
 * Contracts:
 * - Data flows through the typed catalog helpers (`@/features/catalogs/api`);
 *   the list renders exactly the entries the server returned (AC-AMS-02).
 * - Mutations are owner/admin on the server; the UI offers row actions only
 *   when the viewer owns the entry or is an administrator, without inferring
 *   permission from the URL. A failed detail fetch surfaces a keyed error.
 * - Scope controls offer only targetable options (managed groups, admin
 *   global); the server stays authoritative and its keyed errors render via
 *   `KosmoErrorAlert`.
 * - Focus continuity: closing the create/edit form or deleting a row lands
 *   focus on a surviving control, never the document body.
 */

const NAME_MAX_LENGTH = 80;
const DESCRIPTION_MAX_LENGTH = 2000;
const INSTRUCTIONS_MAX_LENGTH = 100000;

const SKILL_REQUEST_FAILED = "SKILL_REQUEST_FAILED";

/** Column layout: name, description, scope, then the trailing actions track. */
const LIST_GRID_TEMPLATE = "minmax(0,1.1fr) minmax(0,2fr) minmax(0,0.9fr) auto";

type FormTarget = { mode: "create" } | { mode: "edit"; entryId: string; rowIndex: number };

function isCatalogScope(value: unknown): value is CatalogScope {
  return value === "personal" || value === "group" || value === "global";
}

export function SkillsPage() {
  const { t } = useTranslation();
  const { user, capabilities } = useCurrentUser();
  const [rows, setRows] = useState<SkillCatalogEntry[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<KosmoError | null>(null);
  const [formTarget, setFormTarget] = useState<FormTarget | null>(null);
  const [deleteTarget, setDeleteTarget] = useState<SkillCatalogEntry | null>(null);
  const [deleting, setDeleting] = useState(false);
  const [deleteError, setDeleteError] = useState<KosmoError | null>(null);

  // Focus continuity for keyboard users. `ConfirmDialog` restores focus to
  // the delete row action on close, but a successful delete (or the form
  // swap, which unmounts the whole list) removes that element during the
  // refresh. The opener element and the affected row's index are captured so
  // the post-refresh effect can land focus on a surviving control instead of
  // the document body.
  const deleteOpenerRef = useRef<HTMLElement | null>(null);
  const pendingFocusRef = useRef<{ opener: HTMLElement | null; rowIndex: number | null } | null>(null);
  const formOpenerRef = useRef<HTMLElement | null>(null);
  const formRowIndexRef = useRef<number | null>(null);
  // The list section element stands in for a list ref: `CatalogList` owns the
  // `ul` internally, so focus restoration resolves rows through the section.
  const sectionRef = useRef<HTMLElement>(null);
  const addButtonRef = useRef<HTMLButtonElement>(null);

  const isAdmin = capabilities?.scopes.global ?? false;
  const managedGroups: CatalogManagedGroup[] = capabilities?.groups ?? [];

  const canManage = useCallback(
    (entry: SkillCatalogEntry) => isAdmin || entry.owner_user_id === user?.id,
    [isAdmin, user?.id],
  );

  const load = useCallback(async (options?: { silent?: boolean }) => {
    // Silent refreshes (after a row action) keep the list mounted so Radix
    // can restore focus to the originating action button.
    if (!options?.silent) setLoading(true);
    setError(null);
    try {
      setRows(await fetchSkills());
    } catch (cause) {
      setError(toKosmoError(cause, SKILL_REQUEST_FAILED));
    } finally {
      if (!options?.silent) setLoading(false);
    }
  }, []);
  useEffect(() => {
    void load();
  }, [load]);

  useEffect(() => {
    const pending = pendingFocusRef.current;
    if (!pending || formTarget !== null) return;
    pendingFocusRef.current = null;
    // ConfirmDialog already restored focus to the opener when the row still
    // exists (e.g. a failed delete); leave it alone in that case.
    if (pending.opener?.isConnected) return;
    const items =
      sectionRef.current?.querySelectorAll<HTMLElement>(":scope ul > li") ?? [];
    const row =
      pending.rowIndex !== null && items.length > 0
        ? items[Math.min(Math.max(pending.rowIndex, 0), items.length - 1)]
        : null;
    const action = row?.querySelector<HTMLElement>('[data-slot="row-actions"] button') ?? null;
    if (action) action.focus();
    else addButtonRef.current?.focus();
  }, [rows, formTarget]);

  /** Opens the create/edit form, remembering where focus came from. */
  function openForm(target: FormTarget) {
    pendingFocusRef.current = null;
    formOpenerRef.current =
      document.activeElement instanceof HTMLElement ? document.activeElement : null;
    formRowIndexRef.current = target.mode === "edit" ? target.rowIndex : null;
    setFormTarget(target);
  }

  /** Closes the form and schedules focus restoration; `refetch` after a save. */
  function closeForm(options?: { refetch?: boolean }) {
    pendingFocusRef.current = { opener: formOpenerRef.current, rowIndex: formRowIndexRef.current };
    formOpenerRef.current = null;
    formRowIndexRef.current = null;
    setFormTarget(null);
    if (options?.refetch) void load({ silent: true });
  }

  async function confirmDelete() {
    const target = deleteTarget;
    if (!target || deleting) return;
    setDeleting(true);
    setDeleteError(null);
    try {
      await deleteSkill(target.id);
      // Close before refreshing so focus returns to the row action while the
      // row still exists; the refresh then removes it and the effect above
      // lands focus on a surviving control.
      setDeleteTarget(null);
      pendingFocusRef.current = {
        opener: deleteOpenerRef.current,
        rowIndex: rows.findIndex((item) => item.id === target.id),
      };
      deleteOpenerRef.current = null;
      await load({ silent: true });
    } catch (cause) {
      setDeleteError(toKosmoError(cause, SKILL_REQUEST_FAILED));
      setDeleteTarget(null);
    } finally {
      setDeleting(false);
    }
  }

  if (formTarget) {
    return (
      <section className="mx-auto w-full max-w-7xl flex-1 px-5 py-8 sm:px-8 sm:py-10">
        <SkillForm
          entryId={formTarget.mode === "edit" ? formTarget.entryId : null}
          managedGroups={managedGroups}
          globalAllowed={isAdmin}
          onClose={closeForm}
        />
      </section>
    );
  }

  return (
    <section
      ref={sectionRef}
      className="mx-auto w-full max-w-7xl flex-1 px-5 py-8 sm:px-8 sm:py-10"
    >
      <CatalogPageHeader
        title={t("skills.title")}
        description={t("skills.description")}
        action={
          <Button ref={addButtonRef} onClick={() => openForm({ mode: "create" })} className="w-full sm:w-auto">
            <Icon name="add" />
            {t("common.add")}
          </Button>
        }
      />
      {loading ? (
        <CatalogLoading />
      ) : error ? (
        <CatalogLoadError error={error} onRetry={() => void load()} />
      ) : rows.length === 0 ? (
        <CatalogEmpty
          title={t("skills.emptyTitle")}
          description={t("skills.emptyDescription")}
          action={
            <Button variant="outline" onClick={() => openForm({ mode: "create" })}>
              {t("skills.addFirst")}
            </Button>
          }
        />
      ) : (
        <CatalogList
          className="mt-7"
          columns={[t("skills.columns.name"), t("skills.columns.description"), t("skills.columns.scope")]}
          template={LIST_GRID_TEMPLATE}
        >
          {rows.map((entry, index) => (
            <CatalogRow key={entry.id}>
              <div className="min-w-0">
                <span className="block truncate text-sm font-medium">{entry.name}</span>
                <span className="mt-1 block truncate text-xs text-muted-foreground">
                  {t("skills.columns.owner")}: {entry.owner_user_id}
                </span>
              </div>
              <div className="min-w-0 text-sm text-muted-foreground">
                <span className="block truncate">{entry.description || "—"}</span>
              </div>
              <div className="flex justify-between gap-3 text-sm sm:block">
                <span className="text-muted-foreground sm:hidden">{t("skills.columns.scope")}</span>
                {t(`skills.scope.${entry.visibility}`, { defaultValue: entry.visibility })}
              </div>
              {canManage(entry) ? (
                <RowActions>
                  <RowActionButton
                    icon="edit"
                    label={t("common.edit")}
                    onClick={() => openForm({ mode: "edit", entryId: entry.id, rowIndex: index })}
                  />
                  <RowActionButton
                    icon="delete"
                    label={t("common.delete")}
                    onClick={() => {
                      deleteOpenerRef.current =
                        document.activeElement instanceof HTMLElement ? document.activeElement : null;
                      setDeleteTarget(entry);
                    }}
                  />
                </RowActions>
              ) : null}
            </CatalogRow>
          ))}
        </CatalogList>
      )}
      {deleteError ? (
        <div className="mt-6">
          <KosmoErrorAlert error={deleteError} />
        </div>
      ) : null}
      <ConfirmDialog
        open={deleteTarget !== null}
        onOpenChange={(open) => {
          if (!open) setDeleteTarget(null);
        }}
        title={t("skills.delete.title")}
        description={t("skills.delete.description", { name: deleteTarget?.name ?? "" })}
        confirmLabel={t("common.delete")}
        loading={deleting}
        onConfirm={() => void confirmDelete()}
      />
    </section>
  );
}

type FieldErrors = {
  name?: string;
  description?: string;
  instructions?: string;
  scope?: string;
};

/**
 * The create/edit surface. Edit hydrates from the detail endpoint first: a
 * stale list row must never mask an entry that has since become invisible or
 * was changed elsewhere, so a failed fetch surfaces a keyed error instead of
 * a pre-filled form.
 */
function SkillForm({
  entryId,
  managedGroups,
  globalAllowed,
  onClose,
}: {
  entryId: string | null;
  managedGroups: CatalogManagedGroup[];
  globalAllowed: boolean;
  onClose: (options: { refetch: boolean }) => void;
}) {
  const { t } = useTranslation();
  const [detail, setDetail] = useState<SkillCatalogEntry | null>(null);
  const [detailError, setDetailError] = useState<KosmoError | null>(null);
  const [loading, setLoading] = useState(entryId !== null);

  useEffect(() => {
    if (entryId === null) return;
    let active = true;
    setLoading(true);
    setDetailError(null);
    fetchSkill(entryId)
      .then((data) => {
        if (active) setDetail(data);
      })
      .catch((cause) => {
        if (active) setDetailError(toKosmoError(cause, SKILL_REQUEST_FAILED));
      })
      .finally(() => {
        if (active) setLoading(false);
      });
    return () => {
      active = false;
    };
  }, [entryId]);

  if (detailError) {
    return (
      <div className="mt-6 space-y-3">
        <KosmoErrorAlert error={detailError} />
        <div>
          <Button variant="outline" onClick={() => onClose({ refetch: false })}>
            {t("skills.form.back")}
          </Button>
        </div>
      </div>
    );
  }
  if (loading) return <CatalogLoading />;
  return (
    <SkillFormFields
      initial={detail}
      managedGroups={managedGroups}
      globalAllowed={globalAllowed}
      onClose={onClose}
    />
  );
}

/**
 * The form body, mounted once its `initial` data is final so field state is
 * initialized exactly once (create: empty; edit: the fetched detail).
 */
function SkillFormFields({
  initial,
  managedGroups,
  globalAllowed,
  onClose,
}: {
  initial: SkillCatalogEntry | null;
  managedGroups: CatalogManagedGroup[];
  globalAllowed: boolean;
  onClose: (options: { refetch: boolean }) => void;
}) {
  const { t } = useTranslation();
  const formRef = useCatalogFormFocus();
  const isEdit = initial !== null;
  const [name, setName] = useState(initial?.name ?? "");
  const [description, setDescription] = useState(initial?.description ?? "");
  const [instructions, setInstructions] = useState(initial?.instructions ?? "");
  const [scope, setScope] = useState<CatalogScope>(
    isCatalogScope(initial?.visibility) ? initial.visibility : "personal",
  );
  const [groupId, setGroupId] = useState(initial?.group_id ?? "");
  const [errors, setErrors] = useState<FieldErrors>({});
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<KosmoError | null>(null);

  function validate(): FieldErrors {
    const next: FieldErrors = {};
    const trimmed = name.trim();
    if (trimmed.length < 1 || trimmed.length > NAME_MAX_LENGTH) {
      next.name = t("errors.skill.name_invalid");
    }
    if (description.length > DESCRIPTION_MAX_LENGTH) {
      next.description = t("errors.skill.description_invalid", { max_length: DESCRIPTION_MAX_LENGTH });
    }
    if (instructions.length > INSTRUCTIONS_MAX_LENGTH) {
      next.instructions = t("errors.skill.instructions_invalid", { max_length: INSTRUCTIONS_MAX_LENGTH });
    }
    // The server stays authoritative for who may target which scope; this
    // only blocks the incomplete group choice (no group picked yet).
    if (scope === "group" && groupId === "") {
      next.scope = t("errors.skill.scope_invalid");
    }
    return next;
  }

  async function handleSubmit(event: FormEvent) {
    event.preventDefault();
    if (saving) return;
    const nextErrors = validate();
    setErrors(nextErrors);
    if (Object.values(nextErrors).some((message) => message !== undefined)) return;
    setSaving(true);
    setError(null);
    const body = {
      name: name.trim(),
      visibility: scope,
      group_id: scope === "group" ? groupId : null,
      description,
      instructions,
    };
    try {
      if (initial) await updateSkill(initial.id, body);
      else await createSkill(body);
      onClose({ refetch: true });
    } catch (cause) {
      setError(toKosmoError(cause, SKILL_REQUEST_FAILED));
    } finally {
      setSaving(false);
    }
  }

  return (
    <div>
      <div>
        <h1 className="text-2xl font-semibold tracking-tight text-balance">
          {isEdit ? t("skills.form.editTitle") : t("skills.form.createTitle")}
        </h1>
        <p className="mt-1 max-w-2xl text-sm leading-6 text-muted-foreground">
          {isEdit ? t("skills.form.editDescription") : t("skills.form.createDescription")}
        </p>
      </div>
      <form ref={formRef} className="mt-8 grid max-w-3xl gap-6" onSubmit={handleSubmit} noValidate>
        {error ? <KosmoErrorAlert error={error} /> : null}
        <CatalogField
          label={t("skills.form.name")}
          hint={t("skills.form.nameHint", { max: NAME_MAX_LENGTH })}
          error={errors.name}
        >
          <Input
            value={name}
            onChange={(event) => setName(event.target.value)}
            maxLength={NAME_MAX_LENGTH}
            placeholder={t("skills.form.namePlaceholder")}
            autoComplete="off"
          />
        </CatalogField>
        <CatalogField
          label={t("skills.form.description")}
          hint={t("skills.form.descriptionHint", { max: DESCRIPTION_MAX_LENGTH })}
          error={errors.description}
        >
          <CatalogTextArea
            rows={3}
            className="font-sans"
            value={description}
            onChange={(event) => setDescription(event.target.value)}
            placeholder={t("skills.form.descriptionPlaceholder")}
          />
        </CatalogField>
        <InstructionsEditor
          value={instructions}
          onChange={setInstructions}
          error={errors.instructions}
          disabled={saving}
        />
        <div className="grid gap-1.5">
          <CatalogScopeField
            scope={scope}
            onScopeChange={(next) => {
              setScope(next);
              setErrors((current) => ({ ...current, scope: undefined }));
            }}
            groupId={groupId}
            onGroupIdChange={(next) => {
              setGroupId(next);
              setErrors((current) => ({ ...current, scope: undefined }));
            }}
            managedGroups={managedGroups}
            globalAllowed={globalAllowed}
          />
          {errors.scope ? (
            <p role="alert" className="text-xs leading-5 text-destructive">
              {errors.scope}
            </p>
          ) : null}
        </div>
        <div className="flex flex-col gap-3 sm:flex-row">
          <Button
            type="button"
            variant="outline"
            disabled={saving}
            onClick={() => onClose({ refetch: false })}
          >
            {t("common.cancel")}
          </Button>
          <Button type="submit" loading={saving}>
            {t("skills.form.save")}
          </Button>
        </div>
      </form>
    </div>
  );
}

/**
 * Markdown instructions editor: a monospace writing surface plus a Write /
 * Preview toggle. Preview renders through `MarkdownPreview` (safe renderer;
 * no HTML, scheme-allowlisted links, no remote resources) and never feeds
 * the text back into the form — switching back restores the exact source.
 */
function InstructionsEditor({
  value,
  onChange,
  error,
  disabled = false,
}: {
  value: string;
  onChange: (next: string) => void;
  error?: string;
  disabled?: boolean;
}) {
  const { t } = useTranslation();
  const idPrefix = useId();
  const controlId = `${idPrefix}-control`;
  const hintId = `${idPrefix}-hint`;
  const errorId = `${idPrefix}-error`;
  const [view, setView] = useState<"write" | "preview">("write");
  const describedBy = [hintId, error ? errorId : undefined].filter(Boolean).join(" ") || undefined;

  const toggleClasses = (active: boolean) =>
    cn(
      "inline-flex h-7 items-center rounded-md px-3 text-xs font-medium outline-none transition-colors",
      "focus-visible:ring-[3px] focus-visible:ring-ring/50",
      active ? "bg-background text-foreground shadow-xs" : "text-muted-foreground hover:text-foreground",
    );

  return (
    <div className="grid min-w-0 gap-1.5">
      <div className="flex flex-wrap items-center justify-between gap-2">
        {view === "write" ? (
          <label htmlFor={controlId} className="text-sm font-medium">
            {t("skills.form.instructions")}
          </label>
        ) : (
          <span className="text-sm font-medium">{t("skills.form.instructions")}</span>
        )}
        <div role="group" aria-label={t("skills.form.editorView")} className="flex gap-0.5 rounded-lg bg-muted p-0.5">
          <button
            type="button"
            aria-pressed={view === "write"}
            onClick={() => setView("write")}
            className={toggleClasses(view === "write")}
          >
            {t("skills.form.write")}
          </button>
          <button
            type="button"
            aria-pressed={view === "preview"}
            onClick={() => setView("preview")}
            className={toggleClasses(view === "preview")}
          >
            {t("skills.form.preview")}
          </button>
        </div>
      </div>
      {view === "write" ? (
        <CatalogTextArea
          id={controlId}
          rows={12}
          value={value}
          onChange={(event) => onChange(event.target.value)}
          disabled={disabled}
          aria-invalid={error ? true : undefined}
          aria-describedby={describedBy}
        />
      ) : (
        <div
          data-slot="instructions-preview"
          className="min-h-64 rounded-lg border border-input bg-background px-3 py-2"
        >
          <MarkdownPreview source={value} />
        </div>
      )}
      <p id={hintId} className="text-xs leading-5 text-muted-foreground">
        {t("skills.form.instructionsHint", { max: INSTRUCTIONS_MAX_LENGTH })}
      </p>
      {error ? (
        <p id={errorId} role="alert" className="text-xs leading-5 text-destructive">
          {error}
        </p>
      ) : null}
    </div>
  );
}

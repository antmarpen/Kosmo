import { type FormEvent, useCallback, useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";

import { toKosmoError } from "@/api/apiError";
import { ConfirmDialog } from "@/components/ConfirmDialog";
import { KosmoErrorAlert, type KosmoError } from "@/components/KosmoErrorAlert";
import { RowActions, RowActionButton } from "@/components/RowActions";
import { Button } from "@/components/ui/button";
import { Icon } from "@/components/ui/icon";
import { Input } from "@/components/ui/input";
import { CatalogField } from "@/features/catalogs/components/CatalogField";
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
  createMcp,
  deleteMcp,
  fetchMcp,
  fetchMcps,
  updateMcp,
} from "@/features/catalogs/api";
import type { McpCatalogEntry, McpCatalogListEntry } from "@/features/catalogs/catalogTypes";
import { useCurrentUser } from "@/features/auth/useCurrentUser";
import { McpTransportForm } from "./McpTransportForm";
import {
  buildTransportPayload,
  createTransportDraft,
  transportFromDetail,
  type TransportDraft,
  type TransportErrors,
} from "./transportState";

/**
 * WP-14 — MCP server catalog screen (`/admin/mcps`): scoped list, create,
 * edit and delete with discriminated transport authoring and write-only
 * secret interaction.
 *
 * Contracts:
 * - Data flows through the typed catalog helpers (`@/features/catalogs/api`);
 *   the list renders exactly the entries the server returned (AC-AMS-02).
 * - Mutations are owner/admin on the server; the UI offers row actions only
 *   when the viewer owns the entry or is an administrator, without inferring
 *   permission from the URL. A failed detail fetch surfaces a keyed error.
 * - Transport and entries are authored through `McpTransportForm` and turned
 *   into the exact `replace`/`keep`/`remove` request set by
 *   `buildTransportPayload`. Stored secrets are never preloaded — the masked
 *   input starts empty with an `is_set` presence marker, and a blank value
 *   means "keep". No secret value is logged, persisted, or sent as a
 *   placeholder (AC-AMS-07).
 * - Scope controls offer only targetable options (managed groups, admin
 *   global); the server stays authoritative and its keyed errors render via
 *   `KosmoErrorAlert`.
 * - Focus continuity: closing the create/edit form or deleting a row lands
 *   focus on a surviving control, never the document body.
 */

const NAME_MAX_LENGTH = 80;

const MCP_REQUEST_FAILED = "MCP_SERVER_REQUEST_FAILED";

/** Column layout: name, scope, then the trailing actions track. */
const LIST_GRID_TEMPLATE = "minmax(0,1.6fr) minmax(0,1fr) auto";

type FormTarget = { mode: "create" } | { mode: "edit"; entryId: string; rowIndex: number };

function isCatalogScope(value: unknown): value is CatalogScope {
  return value === "personal" || value === "group" || value === "global";
}

export function McpServersPage() {
  const { t } = useTranslation();
  const { user, capabilities } = useCurrentUser();
  const [rows, setRows] = useState<McpCatalogListEntry[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<KosmoError | null>(null);
  const [formTarget, setFormTarget] = useState<FormTarget | null>(null);
  const [deleteTarget, setDeleteTarget] = useState<McpCatalogListEntry | null>(null);
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
    (entry: McpCatalogListEntry) => isAdmin || entry.owner_user_id === user?.id,
    [isAdmin, user?.id],
  );

  const load = useCallback(async (options?: { silent?: boolean }) => {
    // Silent refreshes (after a row action) keep the list mounted so Radix
    // can restore focus to the originating action button.
    if (!options?.silent) setLoading(true);
    setError(null);
    try {
      setRows(await fetchMcps());
    } catch (cause) {
      setError(toKosmoError(cause, MCP_REQUEST_FAILED));
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
      await deleteMcp(target.id);
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
      setDeleteError(toKosmoError(cause, MCP_REQUEST_FAILED));
      setDeleteTarget(null);
    } finally {
      setDeleting(false);
    }
  }

  if (formTarget) {
    return (
      <section className="mx-auto w-full max-w-7xl flex-1 px-5 py-8 sm:px-8 sm:py-10">
        <McpServerForm
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
        title={t("mcps.title")}
        description={t("mcps.description")}
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
          title={t("mcps.emptyTitle")}
          description={t("mcps.emptyDescription")}
          action={
            <Button variant="outline" onClick={() => openForm({ mode: "create" })}>
              {t("mcps.addFirst")}
            </Button>
          }
        />
      ) : (
        <CatalogList
          className="mt-7"
          columns={[t("mcps.columns.name"), t("mcps.columns.scope")]}
          template={LIST_GRID_TEMPLATE}
        >
          {rows.map((entry, index) => (
            <CatalogRow key={entry.id}>
              <div className="min-w-0">
                <span className="block truncate text-sm font-medium">{entry.name}</span>
                <span className="mt-1 block truncate text-xs text-muted-foreground">
                  {t("mcps.columns.owner")}: {entry.owner_user_id}
                </span>
              </div>
              <div className="flex justify-between gap-3 text-sm sm:block">
                <span className="text-muted-foreground sm:hidden">{t("mcps.columns.scope")}</span>
                {t(`mcps.scope.${entry.visibility}`, { defaultValue: entry.visibility })}
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
        title={t("mcps.delete.title")}
        description={t("mcps.delete.description", { name: deleteTarget?.name ?? "" })}
        confirmLabel={t("common.delete")}
        loading={deleting}
        onConfirm={() => void confirmDelete()}
      />
    </section>
  );
}

/** The list endpoint returns metadata-only rows (no transport). */
type FieldErrors = {
  name?: string;
  scope?: string;
};

/**
 * The create/edit surface. Edit hydrates from the detail endpoint first: a
 * stale list row must never mask an entry that has since become invisible or
 * was changed elsewhere, so a failed fetch surfaces a keyed error instead of
 * a pre-filled form.
 */
function McpServerForm({
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
  const [detail, setDetail] = useState<McpCatalogEntry | null>(null);
  const [detailError, setDetailError] = useState<KosmoError | null>(null);
  const [loading, setLoading] = useState(entryId !== null);

  useEffect(() => {
    if (entryId === null) return;
    let active = true;
    setLoading(true);
    setDetailError(null);
    fetchMcp(entryId)
      .then((data) => {
        if (active) setDetail(data);
      })
      .catch((cause) => {
        if (active) setDetailError(toKosmoError(cause, MCP_REQUEST_FAILED));
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
            {t("mcps.form.back")}
          </Button>
        </div>
      </div>
    );
  }
  if (loading) return <CatalogLoading />;
  return (
    <McpServerFormFields
      initial={detail}
      managedGroups={managedGroups}
      globalAllowed={globalAllowed}
      onClose={onClose}
    />
  );
}

/**
 * The form body, mounted once its `initial` data is final so field state is
 * initialized exactly once (create: empty; edit: the fetched detail). The
 * transport draft hydrates from the detail transport — stored secrets arrive
 * only as presence markers, never as values.
 */
function McpServerFormFields({
  initial,
  managedGroups,
  globalAllowed,
  onClose,
}: {
  initial: McpCatalogEntry | null;
  managedGroups: CatalogManagedGroup[];
  globalAllowed: boolean;
  onClose: (options: { refetch: boolean }) => void;
}) {
  const { t } = useTranslation();
  const isEdit = initial !== null;
  const [name, setName] = useState(initial?.name ?? "");
  const [scope, setScope] = useState<CatalogScope>(
    isCatalogScope(initial?.visibility) ? initial.visibility : "personal",
  );
  const [groupId, setGroupId] = useState(initial?.group_id ?? "");
  const [transport, setTransport] = useState<TransportDraft>(() =>
    initial ? transportFromDetail(initial.transport) : createTransportDraft("stdio"),
  );
  const [transportErrors, setTransportErrors] = useState<TransportErrors | null>(null);
  const [errors, setErrors] = useState<FieldErrors>({});
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<KosmoError | null>(null);

  function handleTransportChange(next: TransportDraft) {
    // Stale client validation must not linger over changed authoring.
    setTransportErrors(null);
    setTransport(next);
  }

  function validate(): FieldErrors {
    const next: FieldErrors = {};
    const trimmed = name.trim();
    if (trimmed.length < 1 || trimmed.length > NAME_MAX_LENGTH) {
      next.name = t("errors.mcp_server.name_invalid");
    }
    // The server stays authoritative for who may target which scope; this
    // only blocks the incomplete group choice (no group picked yet).
    if (scope === "group" && groupId === "") {
      next.scope = t("errors.mcp_server.scope_invalid");
    }
    return next;
  }

  async function handleSubmit(event: FormEvent) {
    event.preventDefault();
    if (saving) return;
    const nextErrors = validate();
    setErrors(nextErrors);
    if (Object.values(nextErrors).some((message) => message !== undefined)) return;
    // The exact entry set is derived here: replace/keep/remove actions,
    // retention for untouched stored secrets, and rename/classification
    // validations surfaced before anything is sent.
    const outcome = buildTransportPayload(transport, {
      nameChanged: isEdit && name.trim() !== initial.name,
    });
    if (!outcome.ok) {
      setTransportErrors(outcome.errors);
      return;
    }
    setTransportErrors(null);
    setSaving(true);
    setError(null);
    const body = {
      name: name.trim(),
      visibility: scope,
      group_id: scope === "group" ? groupId : null,
      transport: outcome.transport,
    };
    try {
      if (initial) await updateMcp(initial.id, body);
      else await createMcp(body);
      onClose({ refetch: true });
    } catch (cause) {
      setError(toKosmoError(cause, MCP_REQUEST_FAILED));
    } finally {
      setSaving(false);
    }
  }

  return (
    <div>
      <div>
        <h1 className="text-2xl font-semibold tracking-tight text-balance">
          {isEdit ? t("mcps.form.editTitle") : t("mcps.form.createTitle")}
        </h1>
        <p className="mt-1 max-w-2xl text-sm leading-6 text-muted-foreground">
          {isEdit ? t("mcps.form.editDescription") : t("mcps.form.createDescription")}
        </p>
      </div>
      <form className="mt-8 grid max-w-3xl gap-6" onSubmit={handleSubmit} noValidate>
        {error ? <KosmoErrorAlert error={error} /> : null}
        <CatalogField
          label={t("mcps.form.name")}
          hint={t("mcps.form.nameHint", { max: NAME_MAX_LENGTH })}
          error={errors.name}
        >
          <Input
            value={name}
            onChange={(event) => setName(event.target.value)}
            maxLength={NAME_MAX_LENGTH}
            placeholder={t("mcps.form.namePlaceholder")}
            autoComplete="off"
          />
        </CatalogField>
        <McpTransportForm
          transport={transport}
          onChange={handleTransportChange}
          errors={transportErrors}
          saving={saving}
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
            {t("mcps.form.save")}
          </Button>
        </div>
      </form>
    </div>
  );
}

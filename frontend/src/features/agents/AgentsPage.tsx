import { type FormEvent, useCallback, useEffect, useId, useRef, useState } from "react";
import { useTranslation } from "react-i18next";

import { api } from "@/api/auth";
import { toKosmoError, unwrap } from "@/api/apiError";
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
  CatalogSearchSelect,
  type CatalogSelectOption,
} from "@/features/catalogs/components/CatalogSearchSelect";
import {
  createAgent,
  deleteAgent,
  fetchAgent,
  fetchAgents,
  fetchMcps,
  fetchSkills,
  updateAgent,
} from "@/features/catalogs/api";
import type { AgentCatalogEntry } from "@/features/catalogs/catalogTypes";
import { useCurrentUser } from "@/features/auth/useCurrentUser";
import { cn } from "@/lib/utils";

/**
 * WP-15 — Agent catalog screen (`/admin/agents`): scoped list, create, edit
 * and delete with model selection, bounded reasoning effort, a Markdown
 * instructions editor and ordered MCP/skill default references.
 *
 * Contracts:
 * - Data flows through the typed catalog helpers (`@/features/catalogs/api`);
 *   the list renders exactly the entries the server returned (AC-AMS-02).
 * - Mutations are owner/admin on the server; the UI offers row actions only
 *   when the viewer owns the entry or is an administrator, without inferring
 *   permission from the URL. A failed detail fetch surfaces a keyed error.
 * - The runtime is fixed (`opencode`, rendered read-only). The model reuses
 *   the provider model-discovery API without naming a provider instance
 *   (`config_id: null` resolves the caller's own configuration server-side)
 *   plus the explicit `default` convention; discovery failure degrades to
 *   that default instead of blocking authoring. Reasoning effort offers the
 *   v2-advertised value set plus an explicit "use runtime default" (null);
 *   an unrecognized stored value is preserved with a clear unsupported
 *   indication, never silently normalized.
 * - References are searched, ordered selections. Values that no longer
 *   resolve render as unavailable removable chips and survive unrelated
 *   edits: a central save always submits the full authored state (AC-AMS-04).
 * - Editing an agent is a live central change: the form copy explains that
 *   referencing nodes pick the change up on their next run, with no
 *   propagation controls.
 * - Focus continuity: closing the create/edit form or deleting a row lands
 *   focus on a surviving control, never the document body.
 */

const NAME_MAX_LENGTH = 80;
const MODEL_MAX_LENGTH = 300;
const INSTRUCTIONS_MAX_LENGTH = 100000;

const AGENT_REQUEST_FAILED = "AGENT_REQUEST_FAILED";

/**
 * Reasoning effort values the OpenCode v2 runtime advertises for a model
 * (WP-01/WP-19 evidence). This is the runtime's bounded set, not a guessed
 * universal enum; a stored value outside it is preserved and marked.
 */
const REASONING_EFFORT_VALUES = ["none", "low", "medium", "high", "max", "default"] as const;

/** Column layout: name, model, scope, then the trailing actions track. */
const LIST_GRID_TEMPLATE = "minmax(0,1.1fr) minmax(0,1.4fr) minmax(0,0.9fr) auto";

type FormTarget = { mode: "create" } | { mode: "edit"; entryId: string; rowIndex: number };

/** Body of the provider saved-config model-discovery endpoint (typed `unknown` upstream). */
type ModelDiscovery = { valid: boolean; models?: string[] };

function isCatalogScope(value: unknown): value is CatalogScope {
  return value === "personal" || value === "group" || value === "global";
}

export function AgentsPage() {
  const { t } = useTranslation();
  const { user, capabilities } = useCurrentUser();
  const [rows, setRows] = useState<AgentCatalogEntry[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<KosmoError | null>(null);
  const [formTarget, setFormTarget] = useState<FormTarget | null>(null);
  const [deleteTarget, setDeleteTarget] = useState<AgentCatalogEntry | null>(null);
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
    (entry: AgentCatalogEntry) => isAdmin || entry.owner_user_id === user?.id,
    [isAdmin, user?.id],
  );

  const load = useCallback(async (options?: { silent?: boolean }) => {
    // Silent refreshes (after a row action) keep the list mounted so Radix
    // can restore focus to the originating action button.
    if (!options?.silent) setLoading(true);
    setError(null);
    try {
      setRows(await fetchAgents());
    } catch (cause) {
      setError(toKosmoError(cause, AGENT_REQUEST_FAILED));
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
      await deleteAgent(target.id);
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
      setDeleteError(toKosmoError(cause, AGENT_REQUEST_FAILED));
      setDeleteTarget(null);
    } finally {
      setDeleting(false);
    }
  }

  if (formTarget) {
    return (
      <section className="mx-auto w-full max-w-7xl flex-1 px-5 py-8 sm:px-8 sm:py-10">
        <AgentForm
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
        title={t("agents.title")}
        description={t("agents.description")}
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
          title={t("agents.emptyTitle")}
          description={t("agents.emptyDescription")}
          action={
            <Button variant="outline" onClick={() => openForm({ mode: "create" })}>
              {t("agents.addFirst")}
            </Button>
          }
        />
      ) : (
        <CatalogList
          className="mt-7"
          columns={[t("agents.columns.name"), t("agents.columns.model"), t("agents.columns.scope")]}
          template={LIST_GRID_TEMPLATE}
        >
          {rows.map((entry, index) => (
            <CatalogRow key={entry.id}>
              <div className="min-w-0">
                <span className="block truncate text-sm font-medium">{entry.name}</span>
                <span className="mt-1 block truncate text-xs text-muted-foreground">
                  {t("agents.columns.owner")}: {entry.owner_user_id}
                </span>
              </div>
              <div className="min-w-0 text-sm text-muted-foreground">
                <span className="block truncate">
                  {entry.model === "default" ? t("agents.form.modelDefault") : entry.model}
                </span>
              </div>
              <div className="flex justify-between gap-3 text-sm sm:block">
                <span className="text-muted-foreground sm:hidden">{t("agents.columns.scope")}</span>
                {t(`agents.scope.${entry.visibility}`, { defaultValue: entry.visibility })}
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
        title={t("agents.delete.title")}
        description={t("agents.delete.description", { name: deleteTarget?.name ?? "" })}
        confirmLabel={t("common.delete")}
        loading={deleting}
        onConfirm={() => void confirmDelete()}
      />
    </section>
  );
}

type FieldErrors = {
  name?: string;
  model?: string;
  instructions?: string;
  scope?: string;
};

/**
 * The create/edit surface. The detail fetch, the visible MCP/skill options
 * and the model discovery are independent, so they run in parallel and each
 * failure degrades only its own field: a stale reference stays authorable as
 * an unavailable chip and model discovery failure leaves the explicit
 * `default` convention available (AC-AMS-02).
 */
function AgentForm({
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
  const [detail, setDetail] = useState<AgentCatalogEntry | null>(null);
  const [detailError, setDetailError] = useState<KosmoError | null>(null);
  const [loading, setLoading] = useState(entryId !== null);
  const [mcpOptions, setMcpOptions] = useState<CatalogSelectOption[] | null>(null);
  const [mcpOptionsError, setMcpOptionsError] = useState<KosmoError | null>(null);
  const [skillOptions, setSkillOptions] = useState<CatalogSelectOption[] | null>(null);
  const [skillOptionsError, setSkillOptionsError] = useState<KosmoError | null>(null);
  const [models, setModels] = useState<string[] | null>(null);
  const [modelsError, setModelsError] = useState<KosmoError | null>(null);

  useEffect(() => {
    let active = true;
    fetchMcps()
      .then((rows) => {
        if (active) setMcpOptions(rows.map((row) => ({ id: row.id, name: row.name })));
      })
      .catch((cause) => {
        if (active) setMcpOptionsError(toKosmoError(cause, AGENT_REQUEST_FAILED));
      });
    fetchSkills()
      .then((rows) => {
        if (active) {
          setSkillOptions(
            rows.map((row) => ({ id: row.id, name: row.name, description: row.description })),
          );
        }
      })
      .catch((cause) => {
        if (active) setSkillOptionsError(toKosmoError(cause, AGENT_REQUEST_FAILED));
      });
    // Reuse the provider model-discovery API without naming a provider
    // instance: `config_id: null` resolves the caller's own saved
    // configuration server-side (the established personal-scope fallback).
    // A stored configuration that no longer validates contributes no models.
    void (async () => {
      try {
        const response = unwrap(
          await api.POST("/providers/opencode/config/verify", { body: { config_id: null } }),
        ) as ModelDiscovery;
        if (active) setModels(response.valid ? response.models ?? [] : []);
      } catch (cause) {
        if (active) setModelsError(toKosmoError(cause, AGENT_REQUEST_FAILED));
      }
    })();
    if (entryId !== null) {
      setLoading(true);
      setDetailError(null);
      fetchAgent(entryId)
        .then((data) => {
          if (active) setDetail(data);
        })
        .catch((cause) => {
          if (active) setDetailError(toKosmoError(cause, AGENT_REQUEST_FAILED));
        })
        .finally(() => {
          if (active) setLoading(false);
        });
    }
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
            {t("agents.form.back")}
          </Button>
        </div>
      </div>
    );
  }
  if (loading) return <CatalogLoading />;
  return (
    <AgentFormFields
      initial={detail}
      mcpOptions={mcpOptions}
      mcpOptionsError={mcpOptionsError}
      skillOptions={skillOptions}
      skillOptionsError={skillOptionsError}
      models={models}
      modelsError={modelsError}
      managedGroups={managedGroups}
      globalAllowed={globalAllowed}
      onClose={onClose}
    />
  );
}

/**
 * The form body, mounted once its `initial` data is final so field state is
 * initialized exactly once (create: defaults; edit: the fetched detail).
 * Field state owns the whole authored surface: a save submits every field so
 * an unrelated edit never silently drops stored references or values.
 */
function AgentFormFields({
  initial,
  mcpOptions,
  mcpOptionsError,
  skillOptions,
  skillOptionsError,
  models,
  modelsError,
  managedGroups,
  globalAllowed,
  onClose,
}: {
  initial: AgentCatalogEntry | null;
  mcpOptions: CatalogSelectOption[] | null;
  mcpOptionsError: KosmoError | null;
  skillOptions: CatalogSelectOption[] | null;
  skillOptionsError: KosmoError | null;
  models: string[] | null;
  modelsError: KosmoError | null;
  managedGroups: CatalogManagedGroup[];
  globalAllowed: boolean;
  onClose: (options: { refetch: boolean }) => void;
}) {
  const { t } = useTranslation();
  const formRef = useCatalogFormFocus();
  const isEdit = initial !== null;
  const [name, setName] = useState(initial?.name ?? "");
  const [scope, setScope] = useState<CatalogScope>(
    isCatalogScope(initial?.visibility) ? initial.visibility : "personal",
  );
  const [groupId, setGroupId] = useState(initial?.group_id ?? "");
  // Mandatory model, defaulting to the explicit `default` convention.
  const [model, setModel] = useState(initial?.model ?? "default");
  // `null` means "use runtime default" — a distinct, submittable state.
  const [reasoning, setReasoning] = useState<string | null>(initial?.reasoning_effort ?? null);
  const [instructions, setInstructions] = useState(initial?.instructions ?? "");
  const [mcpIds, setMcpIds] = useState<string[]>(initial?.mcp_ids ?? []);
  const [skillIds, setSkillIds] = useState<string[]>(initial?.skill_ids ?? []);
  const [errors, setErrors] = useState<FieldErrors>({});
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<KosmoError | null>(null);

  const discoveredModels = models ?? [];
  const modelMissingFromDiscovery = model !== "default" && !discoveredModels.includes(model);
  const modelOptions: CatalogSelectOption[] = [
    { id: "default", name: t("agents.form.modelDefault") },
    ...discoveredModels
      .filter((entry) => entry !== "default")
      .map((entry) => ({ id: entry, name: entry })),
  ];
  // A stored model that discovery does not list stays selectable and visible
  // instead of being normalized away while (or after) discovery settles.
  if (modelMissingFromDiscovery) {
    modelOptions.push({ id: model, name: model });
  }

  function validate(): FieldErrors {
    const next: FieldErrors = {};
    const trimmed = name.trim();
    if (trimmed.length < 1 || trimmed.length > NAME_MAX_LENGTH) {
      next.name = t("errors.agent.name_invalid");
    }
    const trimmedModel = model.trim();
    if (trimmedModel.length < 1 || trimmedModel.length > MODEL_MAX_LENGTH) {
      next.model = t("errors.agent.model_invalid");
    }
    if (instructions.length > INSTRUCTIONS_MAX_LENGTH) {
      next.instructions = t("errors.agent.instructions_invalid", { max_length: INSTRUCTIONS_MAX_LENGTH });
    }
    // The server stays authoritative for who may target which scope; this
    // only blocks the incomplete group choice (no group picked yet).
    if (scope === "group" && groupId === "") {
      next.scope = t("errors.agent.scope_invalid");
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
    // The full authored state, always: a central edit preserves stored
    // fields (including unavailable references and unrecognized values)
    // unless the user changed them. `reasoning_effort: null` explicitly
    // clears the override back to the runtime default. The fixed runtime is
    // sent on create only — the PATCH omits it, so the server keeps it.
    const body = {
      name: name.trim(),
      visibility: scope,
      group_id: scope === "group" ? groupId : null,
      model: model.trim(),
      reasoning_effort: reasoning,
      instructions,
      mcp_ids: mcpIds,
      skill_ids: skillIds,
    };
    try {
      if (initial) await updateAgent(initial.id, body);
      else await createAgent({ ...body, runtime: "opencode" });
      onClose({ refetch: true });
    } catch (cause) {
      setError(toKosmoError(cause, AGENT_REQUEST_FAILED));
    } finally {
      setSaving(false);
    }
  }

  return (
    <div>
      <div>
        <h1 className="text-2xl font-semibold tracking-tight text-balance">
          {isEdit ? t("agents.form.editTitle") : t("agents.form.createTitle")}
        </h1>
        <p className="mt-1 max-w-2xl text-sm leading-6 text-muted-foreground">
          {isEdit ? t("agents.form.editDescription") : t("agents.form.createDescription")}
        </p>
        {isEdit ? (
          <p className="mt-4 max-w-3xl rounded-md border border-border bg-muted/40 px-3 py-2 text-sm leading-6 text-muted-foreground">
            {t("agents.form.liveNote")}
          </p>
        ) : null}
      </div>
      <form ref={formRef} className="mt-8 grid max-w-3xl gap-6" onSubmit={handleSubmit} noValidate>
        {error ? <KosmoErrorAlert error={error} /> : null}
        <CatalogField
          label={t("agents.form.name")}
          hint={t("agents.form.nameHint", { max: NAME_MAX_LENGTH })}
          error={errors.name}
        >
          <Input
            value={name}
            onChange={(event) => setName(event.target.value)}
            maxLength={NAME_MAX_LENGTH}
            placeholder={t("agents.form.namePlaceholder")}
            autoComplete="off"
          />
        </CatalogField>
        <div className="grid min-w-0 gap-1.5">
          <span className="text-sm font-medium">{t("agents.form.runtime")}</span>
          <div className="rounded-lg border border-input bg-muted/40 px-3 py-2 text-sm text-muted-foreground">
            {t("agents.form.runtimeValue")}
          </div>
          <p className="text-xs leading-5 text-muted-foreground">{t("agents.form.runtimeHint")}</p>
        </div>
        <ModelField
          value={model}
          onChange={setModel}
          options={modelOptions}
          models={models}
          modelsError={modelsError}
          preserved={modelMissingFromDiscovery && models !== null}
          error={errors.model}
          disabled={saving}
        />
        <ReasoningField
          value={reasoning}
          onChange={setReasoning}
          disabled={saving}
        />
        <InstructionsEditor
          value={instructions}
          onChange={setInstructions}
          error={errors.instructions}
          disabled={saving}
        />
        <ReferenceField
          label={t("agents.form.mcps")}
          hint={t("agents.form.mcpsHint")}
          options={mcpOptions}
          optionsError={mcpOptionsError}
          value={mcpIds}
          onChange={setMcpIds}
          disabled={saving}
        />
        <ReferenceField
          label={t("agents.form.skills")}
          hint={t("agents.form.skillsHint")}
          options={skillOptions}
          optionsError={skillOptionsError}
          value={skillIds}
          onChange={setSkillIds}
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
            disabled={saving}
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
            {t("agents.form.save")}
          </Button>
        </div>
      </form>
    </div>
  );
}

/**
 * Searchable model selection fed by provider model discovery plus the
 * explicit `default` convention. Discovery failure renders its keyed error
 * inline and keeps the field authorable; a stored model the discovery does
 * not list stays selected with a preserving note.
 */
function ModelField({
  value,
  onChange,
  options,
  models,
  modelsError,
  preserved,
  error,
  disabled = false,
}: {
  value: string;
  onChange: (next: string) => void;
  options: CatalogSelectOption[];
  models: string[] | null;
  modelsError: KosmoError | null;
  preserved: boolean;
  error?: string;
  disabled?: boolean;
}) {
  const { t } = useTranslation();
  const idPrefix = useId();
  const controlId = `${idPrefix}-control`;
  const errorId = `${idPrefix}-error`;
  const loading = models === null && modelsError === null;

  return (
    <div className="grid min-w-0 gap-1.5">
      <label htmlFor={controlId} className="text-sm font-medium">
        {t("agents.form.model")}
      </label>
      <CatalogSearchSelect
        id={controlId}
        mode="single"
        options={options}
        value={value}
        onChange={(next) => {
          // The model is mandatory: a null can only come from the clear
          // affordance, which this field never renders (clearable={false}).
          if (next !== null) onChange(next);
        }}
        clearable={false}
        aria-label={t("agents.form.model")}
        disabled={disabled}
      />
      <p className="text-xs leading-5 text-muted-foreground">
        {loading ? t("catalog.list.loading") : t("agents.form.modelHint")}
      </p>
      {modelsError ? <KosmoErrorAlert error={modelsError} /> : null}
      {preserved ? (
        <p className="text-xs leading-5 text-muted-foreground">{t("agents.form.modelUnlisted")}</p>
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
 * Bounded reasoning-effort choice: an explicit "use runtime default" (null,
 * nothing is requested) plus the values the runtime advertises. A stored
 * value outside the advertised set is preserved as a selectable option with
 * a clear unsupported indication — never silently normalized. Server-side
 * reasoning failures surface through the form-level keyed alert.
 */
function ReasoningField({
  value,
  onChange,
  disabled = false,
}: {
  value: string | null;
  onChange: (next: string | null) => void;
  disabled?: boolean;
}) {
  const { t } = useTranslation();
  const idPrefix = useId();
  const controlId = `${idPrefix}-control`;
  const hintId = `${idPrefix}-hint`;
  const unsupportedId = `${idPrefix}-unsupported`;
  const unsupported = value !== null && !(REASONING_EFFORT_VALUES as readonly string[]).includes(value);
  const describedBy = [hintId, unsupported ? unsupportedId : undefined]
    .filter(Boolean)
    .join(" ");

  return (
    <div className="grid min-w-0 gap-1.5">
      <label htmlFor={controlId} className="text-sm font-medium">
        {t("agents.form.reasoning")}
      </label>
      <select
        id={controlId}
        value={value ?? ""}
        onChange={(event) => onChange(event.target.value === "" ? null : event.target.value)}
        disabled={disabled}
        aria-describedby={describedBy || undefined}
        className={cn(
          "h-9 w-full rounded-lg border border-input bg-background px-3 text-sm shadow-xs outline-none",
          "focus-visible:border-ring focus-visible:ring-[3px] focus-visible:ring-ring/50",
          "disabled:cursor-not-allowed disabled:opacity-50",
        )}
      >
        <option value="">{t("agents.form.reasoningRuntimeDefault")}</option>
        {REASONING_EFFORT_VALUES.map((option) => (
          <option key={option} value={option}>
            {t(`agents.form.reasoningValues.${option}`)}
          </option>
        ))}
        {unsupported ? <option value={value}>{value}</option> : null}
      </select>
      <p id={hintId} className="text-xs leading-5 text-muted-foreground">
        {t("agents.form.reasoningHint")}
      </p>
      {unsupported ? (
        <p id={unsupportedId} className="text-xs leading-5 text-amber-600 dark:text-amber-500">
          {t("agents.form.reasoningUnsupported", { value })}
        </p>
      ) : null}
    </div>
  );
}

/**
 * Searchable ordered multi-selection of visible catalog entries. Values
 * missing from the options (stale references) render as unavailable
 * removable chips inside `CatalogSearchSelect`, so a saved agent whose
 * references disappeared keeps showing them until they are removed
 * deliberately.
 */
function ReferenceField({
  label,
  hint,
  options,
  optionsError,
  value,
  onChange,
  disabled = false,
}: {
  label: string;
  hint: string;
  options: CatalogSelectOption[] | null;
  optionsError: KosmoError | null;
  value: string[];
  onChange: (next: string[]) => void;
  disabled?: boolean;
}) {
  const { t } = useTranslation();
  const loading = options === null && optionsError === null;

  return (
    <div className="grid min-w-0 gap-1.5">
      <span className="text-sm font-medium">{label}</span>
      <CatalogSearchSelect
        mode="multi"
        options={options ?? []}
        value={value}
        onChange={onChange}
        aria-label={label}
        disabled={disabled}
      />
      <p className="text-xs leading-5 text-muted-foreground">
        {loading ? t("catalog.list.loading") : hint}
      </p>
      {optionsError ? <KosmoErrorAlert error={optionsError} /> : null}
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
            {t("agents.form.instructions")}
          </label>
        ) : (
          <span className="text-sm font-medium">{t("agents.form.instructions")}</span>
        )}
        <div role="group" aria-label={t("agents.form.editorView")} className="flex gap-0.5 rounded-lg bg-muted p-0.5">
          <button
            type="button"
            aria-pressed={view === "write"}
            onClick={() => setView("write")}
            className={toggleClasses(view === "write")}
          >
            {t("agents.form.write")}
          </button>
          <button
            type="button"
            aria-pressed={view === "preview"}
            onClick={() => setView("preview")}
            className={toggleClasses(view === "preview")}
          >
            {t("agents.form.preview")}
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
        {t("agents.form.instructionsHint", { max: INSTRUCTIONS_MAX_LENGTH })}
      </p>
      {error ? (
        <p id={errorId} role="alert" className="text-xs leading-5 text-destructive">
          {error}
        </p>
      ) : null}
    </div>
  );
}

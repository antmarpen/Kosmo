import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useNavigate, useParams, useSearchParams } from "react-router";
import { useTranslation } from "react-i18next";
import { api } from "@/api/auth";
import { Button } from "@/components/ui/button";
import { ConfirmDialog } from "@/components/ConfirmDialog";
import { KosmoErrorAlert, type KosmoError, type KosmoErrorDetail } from "@/components/KosmoErrorAlert";
import { Canvas, nodeVisuals } from "./Canvas";
import { ActivateDialog, type PublishedVersionChoice } from "./ActivateDialog";
import { createNode, deleteEdge, deleteNode, deserializeWorkflow, serializeWorkflow, updateNode, type WorkflowDefinition, type WorkflowEdge, type WorkflowEditorState, type WorkflowNode } from "./model";
import { PropertiesPanel } from "./PropertiesPanel";
import { validateWorkflow } from "./validation";
import type { components } from "@/api/schema";

type DraftResponse = components["schemas"]["WorkflowDraftResponse"];
type DraftMetadata = components["schemas"]["WorkflowDraftMetadata"];
type CreatedDraft = { draft_id: string; revision: number };
type SaveDraftResponse = { revision: number; issues?: KosmoErrorDetail[] };
type PublishVersionResponse = components["schemas"]["WorkflowVersionResponse"];
/** Contract of POST /workflows/{workflow_id}/activate (route has no response_model). */
type ActivatedVersion = { version_id: string; active_revision: number };
/**
 * WorkflowResponse plus `publication_revision`. The generated client does not
 * expose the field yet (schema.d.ts is coordinator-owned); the backend already
 * returns it once the list/detail services are updated.
 */
type WorkflowInfo = components["schemas"]["WorkflowResponse"] & { publication_revision: number };
type EditorNotice = { key: string; version?: number };
type PendingConfirmation = { kind: "publish-recent" | "publish-stale-base" | "activate-stale-base"; versionId?: string };

const types: WorkflowNode["type"][] = ["start", "script", "ai", "http", "decision", "workflow", "end"];

function nodeId() { return `node-${globalThis.crypto?.randomUUID?.() ?? `${Date.now()}-${Math.random().toString(36).slice(2)}`}`; }

/** Blank authoring seed used when a draft has no usable definition yet. */
function blankDefinition(name?: string): WorkflowDefinition {
  return { schema_version: "v1", name: name ?? "Untitled workflow", nodes: [createNode("start", "start"), createNode("end", "end")], edges: [] };
}

/**
 * Draft definitions come from the API as opaque JSON. A draft seeded before its
 * workflow had any published version is `{}`; treat anything without a v1 node
 * list as an empty graph and fall back to the blank editor seed.
 */
function toEditorState(definition: unknown, layout: unknown): WorkflowEditorState {
  const candidate = definition as Partial<WorkflowDefinition> | null;
  const usable = !!candidate && candidate.schema_version === "v1" && typeof candidate.name === "string"
    && Array.isArray(candidate.nodes) && candidate.nodes.length > 0 && Array.isArray(candidate.edges);
  const typedLayout = layout && typeof layout === "object" ? (layout as WorkflowEditorState["layout"]) : undefined;
  return deserializeWorkflow(usable ? (candidate as WorkflowDefinition) : blankDefinition(), typedLayout);
}

function unwrap<T>(result: { data?: T; error?: unknown }): T {
  if (result.error || result.data === undefined) throw result.error ?? new Error("Empty API response");
  return result.data;
}

function toKosmoError(cause: unknown): KosmoError {
  const raw = cause as Partial<KosmoError> | undefined;
  return raw && typeof raw.code === "string" && typeof raw.message_key === "string"
    ? { code: raw.code, message_key: raw.message_key, params: raw.params, details: raw.details }
    : { code: "WORKFLOW_EDITOR_FAILED", message_key: "errors.generic" };
}

/** Resolves the draft the editor should load: the requested one, the author's most recent, or a new one. */
async function resolveDraft(workflowId: string, requestedDraftId?: string): Promise<DraftResponse> {
  let draftId = requestedDraftId;
  if (!draftId) {
    const drafts = unwrap(await api.GET("/workflows/{workflow_id}/drafts", { params: { path: { workflow_id: workflowId } } })) as DraftMetadata[];
    if (drafts.length) draftId = drafts[0].id;
    else draftId = (unwrap(await api.POST("/workflows/{workflow_id}/drafts", { params: { path: { workflow_id: workflowId } } })) as CreatedDraft).draft_id;
  }
  return unwrap(await api.GET("/workflows/{workflow_id}/drafts/{draft_id}", { params: { path: { workflow_id: workflowId, draft_id: draftId } } })) as DraftResponse;
}

export function EditorPage() {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const { id } = useParams<{ id: string }>();
  const [searchParams] = useSearchParams();
  const requestedDraftId = searchParams.get("draftId") ?? undefined;

  const [state, setState] = useState<WorkflowEditorState | null>(null);
  const [draftId, setDraftId] = useState<string | null>(requestedDraftId ?? null);
  const [revision, setRevision] = useState<number | null>(null);
  const [status, setStatus] = useState<"loading" | "ready" | "error">("loading");
  const [loadError, setLoadError] = useState<KosmoError | null>(null);
  const [saveError, setSaveError] = useState<KosmoError | null>(null);
  const [validationIssues, setValidationIssues] = useState<KosmoErrorDetail[]>([]);
  const [saving, setSaving] = useState(false);
  const [dirty, setDirty] = useState(false);
  const [paletteOpen, setPaletteOpen] = useState(false);
  const [propertiesOpen, setPropertiesOpen] = useState(false);
  const [counter, setCounter] = useState(0);
  // Publication state: the workflow resource carries the publication revision
  // (publish precondition) and the active version (activation precondition).
  const [workflow, setWorkflow] = useState<WorkflowInfo | null>(null);
  const [lastPublishedVersion, setLastPublishedVersion] = useState<PublishedVersionChoice | null>(null);
  const [publishing, setPublishing] = useState(false);
  const [activating, setActivating] = useState(false);
  const [publishBlocked, setPublishBlocked] = useState(false);
  const [publishError, setPublishError] = useState<KosmoError | null>(null);
  const [activateError, setActivateError] = useState<KosmoError | null>(null);
  const [notices, setNotices] = useState<EditorNotice[]>([]);
  const [activateDialogOpen, setActivateDialogOpen] = useState(false);
  const [pendingConfirmation, setPendingConfirmation] = useState<PendingConfirmation | null>(null);

  // Latest values for callbacks that must stay referentially stable (React Flow
  // re-registers handlers when their identity changes).
  const stateRef = useRef(state);
  stateRef.current = state;
  const requestedDraftIdRef = useRef(requestedDraftId);
  requestedDraftIdRef.current = requestedDraftId;
  // Caches the in-flight resolution so React StrictMode's double effect run
  // loads (and never creates) the draft exactly once.
  const loadRef = useRef<{ key: string; promise: Promise<DraftResponse> } | null>(null);

  useEffect(() => {
    if (!id) {
      setLoadError({ code: "WORKFLOW_EDITOR_FAILED", message_key: "errors.workflow.not_found" });
      setStatus("error");
      return;
    }
    if (loadRef.current?.key !== id) loadRef.current = { key: id, promise: resolveDraft(id, requestedDraftIdRef.current) };
    let active = true;
    loadRef.current.promise.then((draft) => {
      if (!active) return;
      setState(toEditorState(draft.definition, draft.layout));
      setDraftId(draft.id);
      setRevision(draft.revision);
      setStatus("ready");
      setLoadError(null);
      if (!requestedDraftIdRef.current) navigate(`/workflows/${id}/edit?draftId=${encodeURIComponent(draft.id)}`, { replace: true });
    }).catch((cause) => {
      if (!active) return;
      setLoadError(toKosmoError(cause));
      setStatus("error");
    });
    return () => { active = false; };
  }, [id, navigate]);

  const positions = useCallback((next: WorkflowEditorState["layout"]["positions"]) => {
    setState((current) => current ? { ...current, layout: { ...current.layout, positions: next } } : current);
    setDirty(true);
  }, []);
  const selection = useCallback((nodeIds: string[], edge?: WorkflowEdge) => {
    // Below the side-panel breakpoint the properties panel is a bottom sheet;
    // selecting a node must surface it (side panels keep it always visible).
    // Sheets are mutually exclusive: the palette closes so the properties
    // sheet is never covered.
    if (nodeIds.length) { setPaletteOpen(false); setPropertiesOpen(true); }
    setState((current) => {
      if (!current) return current;
      const sameNodes = current.selection.nodeIds.length === nodeIds.length && current.selection.nodeIds.every((nodeIdValue, index) => nodeIdValue === nodeIds[index]);
      const currentEdge = current.selection.edge;
      const sameEdge = (currentEdge === undefined && edge === undefined) || (currentEdge !== undefined && edge !== undefined && currentEdge.from === edge.from && currentEdge.to === edge.to);
      return sameNodes && sameEdge ? current : { ...current, selection: { nodeIds, edge } };
    });
  }, []);
  const connect = useCallback((edge: WorkflowEdge) => {
    setState((current) => current && !current.definition.edges.some((item) => item.from === edge.from && item.to === edge.to)
      ? { ...current, definition: { ...current.definition, edges: [...current.definition.edges, edge] } }
      : current);
    setDirty(true);
  }, []);
  const addNode = (type: WorkflowNode["type"]) => {
    const newId = nodeId();
    setCounter((number) => number + 1);
    setState((current) => current ? { ...current, definition: { ...current.definition, nodes: [...current.definition.nodes, createNode(type, newId)] }, layout: { ...current.layout, positions: { ...current.layout.positions, [newId]: { x: 100 + current.definition.nodes.length * 28, y: 90 + counter * 20 } } }, selection: { nodeIds: [newId] } } : current);
    setDirty(true);
    setPaletteOpen(false);
    setPropertiesOpen(true);
  };
  const deleteSelection = useCallback(() => {
    setState((current) => {
      if (!current) return current;
      if (current.selection.nodeIds.length) return current.selection.nodeIds.reduce((next, selectedId) => deleteNode(next, selectedId), current);
      return current.selection.edge ? deleteEdge(current, current.selection.edge) : current;
    });
    setDirty(true);
  }, []);
  const updateNodeField = useCallback((nodeIdValue: string, patch: Partial<WorkflowNode>) => {
    setState((current) => current ? updateNode(current, nodeIdValue, patch) : current);
    setDirty(true);
  }, []);

  /** Persists the draft; returns false when the save failed or the server reported validation issues. */
  const saveDraft = useCallback(async (): Promise<boolean> => {
    const current = stateRef.current;
    if (!id || !draftId || revision === null || !current) return false;
    setSaving(true);
    setSaveError(null);
    setValidationIssues([]);
    try {
      const result = unwrap(await api.PUT("/workflows/{workflow_id}/drafts/{draft_id}", {
        params: { path: { workflow_id: id, draft_id: draftId }, query: { validate: true } },
        body: { definition: serializeWorkflow(current), layout: current.layout, expected_revision: revision },
      })) as SaveDraftResponse;
      setRevision(result.revision);
      setValidationIssues(result.issues ?? []);
      setDirty(false);
      return (result.issues ?? []).length === 0;
    } catch (cause) {
      setSaveError(toKosmoError(cause));
      return false;
    } finally {
      setSaving(false);
    }
  }, [draftId, id, revision]);

  /** Loads the workflow resource and caches it; throws the flat KosmoError body on failure. */
  const fetchWorkflow = useCallback(async (): Promise<WorkflowInfo | null> => {
    if (!id) return null;
    const loaded = unwrap(await api.GET("/workflows/{workflow_id}", { params: { path: { workflow_id: id } } })) as WorkflowInfo;
    setWorkflow(loaded);
    return loaded;
  }, [id]);

  /**
   * Publishes the saved draft as a new version. Publishing never activates.
   * Optimistic-revision conflicts adopt the returned revision and retry once;
   * the recent-publication and stale-base conflicts require explicit
   * confirmation, so the flow pauses and resends with `confirm_overwrite`.
   */
  const runPublish = useCallback(async (confirmOverwrite: boolean) => {
    const current = stateRef.current;
    if (!id || !draftId || !current || publishing) return;
    if (validateWorkflow(current).level === "error") {
      setPublishBlocked(true);
      return;
    }
    setPublishBlocked(false);
    // The endpoint publishes the saved draft revision, so unsaved editor
    // changes must be persisted first (and may still be rejected by the
    // server-side validation, which aborts the publish).
    if (!confirmOverwrite && dirty) {
      const saved = await saveDraft();
      if (!saved) return;
    }
    setPublishing(true);
    setPublishError(null);
    setNotices([]);
    try {
      const fresh = await fetchWorkflow();
      let publicationRevision = fresh?.publication_revision ?? 0;
      let published: PublishVersionResponse | null = null;
      let attempts = 0;
      while (published === null) {
        attempts += 1;
        try {
          published = unwrap(await api.POST("/workflows/{workflow_id}/drafts/{draft_id}/publish", {
            params: { path: { workflow_id: id, draft_id: draftId } },
            body: { expected_pub_revision: publicationRevision, confirm_overwrite: confirmOverwrite },
          })) as PublishVersionResponse;
        } catch (cause) {
          const error = toKosmoError(cause);
          if (error.message_key === "errors.workflow.publication_revision_conflict") {
            publicationRevision = Number(error.params?.current_revision ?? publicationRevision);
            if (attempts >= 3) throw error;
            setNotices((previous) => [...previous, { key: "workflowEditor.publishWorkflowChanged" }]);
            continue;
          }
          if (!confirmOverwrite && (error.message_key === "errors.workflow.publication_confirmation_required" || error.message_key === "errors.workflow.stale_base_confirmation_required")) {
            setPendingConfirmation({ kind: error.message_key === "errors.workflow.publication_confirmation_required" ? "publish-recent" : "publish-stale-base" });
            return;
          }
          throw error;
        }
      }
      const result = published;
      setLastPublishedVersion({ id: result.id, version: result.version });
      setNotices((previous) => [...previous, { key: "workflowEditor.publishSuccess", version: result.version }]);
      // Refresh the workflow state so the next publish uses the incremented
      // publication revision (the draft itself is unchanged by publishing).
      await fetchWorkflow();
    } catch (cause) {
      setPublishError(toKosmoError(cause));
    } finally {
      setPublishing(false);
    }
  }, [dirty, draftId, fetchWorkflow, id, publishing, saveDraft]);

  /** Opens the activation picker with the freshest workflow state. */
  const openActivate = useCallback(async () => {
    if (!id || activating) return;
    setActivateError(null);
    try {
      await fetchWorkflow();
      setActivateDialogOpen(true);
    } catch (cause) {
      setActivateError(toKosmoError(cause));
    }
  }, [activating, fetchWorkflow, id]);

  /**
   * Activates the chosen published version. Active-revision conflicts adopt
   * the returned revision and retry once; the stale-base conflict pauses for
   * explicit confirmation and resends with `confirm_stale_base`.
   */
  const runActivate = useCallback(async (versionId: string, confirmStaleBase: boolean) => {
    if (!id || activating) return;
    setActivating(true);
    setActivateError(null);
    try {
      const fresh = await fetchWorkflow();
      let expectedActiveRevision = fresh?.active_version?.version ?? 0;
      let activated: ActivatedVersion | null = null;
      let attempts = 0;
      while (activated === null) {
        attempts += 1;
        try {
          activated = unwrap(await api.POST("/workflows/{workflow_id}/activate", {
            params: { path: { workflow_id: id } },
            body: { version_id: versionId, expected_active_revision: expectedActiveRevision, confirm_stale_base: confirmStaleBase },
          })) as ActivatedVersion;
        } catch (cause) {
          const error = toKosmoError(cause);
          if (error.message_key === "errors.workflow.active_revision_conflict") {
            expectedActiveRevision = Number(error.params?.current_revision ?? expectedActiveRevision);
            if (attempts >= 3) throw error;
            continue;
          }
          if (!confirmStaleBase && error.message_key === "errors.workflow.stale_base_confirmation_required") {
            setPendingConfirmation({ kind: "activate-stale-base", versionId });
            return;
          }
          throw error;
        }
      }
      const result = activated;
      setNotices((previous) => [...previous, { key: "workflowEditor.activateSuccess", version: result.active_revision }]);
      setActivateDialogOpen(false);
      // Refresh so the UI reflects the new active version immediately.
      await fetchWorkflow();
    } catch (cause) {
      setActivateError(toKosmoError(cause));
    } finally {
      setActivating(false);
    }
  }, [activating, fetchWorkflow, id]);

  const selectedPosition = useMemo(() => {
    if (!state) return "";
    const selectedId = state.selection.nodeIds[0];
    const position = selectedId ? state.layout.positions[selectedId] : undefined;
    return position ? `${position.x}, ${position.y}` : "";
  }, [state]);

  const validation = useMemo(() => (state ? validateWorkflow(state) : null), [state]);

  // Activation choices: the version published in this session first (the
  // default), then the currently active one. The API exposes no version list,
  // so these are the only versions the editor can name.
  const activateCandidates = useMemo<PublishedVersionChoice[]>(() => {
    const candidates: PublishedVersionChoice[] = [];
    if (lastPublishedVersion) candidates.push(lastPublishedVersion);
    const active = workflow?.active_version;
    if (active && !candidates.some((candidate) => candidate.id === active.id)) candidates.push({ id: active.id, version: active.version });
    return candidates.sort((first, second) => second.version - first.version);
  }, [lastPublishedVersion, workflow]);
  const activateDefaultId = lastPublishedVersion?.id ?? workflow?.active_version?.id ?? null;

  const confirmation = pendingConfirmation;
  const confirmationText = confirmation === null ? null : confirmation.kind === "publish-recent"
    ? { title: "workflowEditor.confirmRecentPublicationTitle", description: "workflowEditor.confirmRecentPublicationDescription", confirmLabel: "workflowEditor.publishAnyway" }
    : confirmation.kind === "publish-stale-base"
      ? { title: "workflowEditor.confirmStaleBasePublishTitle", description: "workflowEditor.confirmStaleBasePublishDescription", confirmLabel: "workflowEditor.publishAnyway" }
      : { title: "workflowEditor.confirmStaleBaseActivateTitle", description: "workflowEditor.confirmStaleBaseActivateDescription", confirmLabel: "workflowEditor.activateAnyway" };

  const ready = status === "ready" && state !== null;
  const busy = publishing || activating;

  return <main className="flex h-[calc(100dvh-3.5rem)] min-h-0 flex-1 flex-col overflow-hidden">
    <header className="flex flex-wrap items-center justify-between gap-3 border-b border-border bg-background px-4 py-3 sm:px-6">
      <div className="flex items-center gap-3"><h1 className="text-lg font-semibold">{t("workflowEditor.title")}</h1><span className="hidden text-xs text-muted-foreground sm:inline">{t("workflowEditor.nodeCount", { count: state?.definition.nodes.length ?? 0 })}</span>{revision !== null && <span className="hidden text-xs text-muted-foreground sm:inline">{t("workflowEditor.revision", { revision })}</span>}</div>
      <div className="flex items-center gap-2">
        {ready && <span role="status" className="text-xs text-muted-foreground">{saving ? t("workflowEditor.saving") : dirty ? t("workflowEditor.unsaved") : t("workflowEditor.saved")}</span>}
        <Button variant="outline" className="lg:hidden" aria-expanded={paletteOpen} onClick={() => { setPropertiesOpen(false); setPaletteOpen((open) => !open); }}>{t("workflowEditor.addNode")}</Button>
        <Button variant="outline" className="lg:hidden" aria-expanded={propertiesOpen} onClick={() => { setPaletteOpen(false); setPropertiesOpen((open) => !open); }}>{t("editor.properties")}</Button>
        <Button variant="outline" disabled={!ready} onClick={deleteSelection}>{t("workflowEditor.deleteSelection")}</Button>
        <Button variant="outline" disabled={!ready || busy} loading={publishing} onClick={() => void runPublish(false)}>{t("workflowEditor.publish" as never)}</Button>
        <Button variant="outline" disabled={!ready || busy} loading={activating} onClick={() => void openActivate()}>{t("workflowEditor.activate" as never)}</Button>
        <Button disabled={!ready || saving || busy} onClick={() => void saveDraft()}>{saving ? t("workflowEditor.saving") : t("workflowEditor.saveDraft")}</Button>
      </div>
    </header>
    {/* Side-by-side panels only once they actually fit next to the shell
        sidebar (lg): at md the three fixed columns left the canvas 0px wide. */}
    {status === "loading" ? <p role="status" className="p-6 text-sm text-muted-foreground">{t("workflowEditor.loading")}</p> : status === "error" || !state ? <div className="p-6"><KosmoErrorAlert error={loadError ?? { code: "WORKFLOW_EDITOR_FAILED", message_key: "errors.generic" }} /></div> : (
      <div className="flex min-h-0 flex-1 flex-col lg:flex-row">
        <aside aria-label={t("workflowEditor.palette")} className={`${paletteOpen ? "fixed inset-x-0 bottom-0 z-20 max-h-[65vh] rounded-t-lg border-t bg-background shadow-lg" : "hidden"} w-full overflow-y-auto p-4 lg:static lg:block lg:w-56 lg:shrink-0 lg:border-r lg:border-t-0 lg:rounded-none lg:shadow-none`}>
          <h2 className="mb-3 text-sm font-semibold">{t("workflowEditor.palette")}</h2>
          <div className="grid grid-cols-2 gap-2 lg:grid-cols-1">{types.map((type) => <button key={type} type="button" aria-label={t("workflowEditor.addType", { type: t(`workflowEditor.types.${type}`) })} onClick={() => addNode(type)} className="flex min-h-10 items-center gap-3 rounded-md border border-border bg-background px-3 text-left text-sm hover:bg-muted focus-visible:outline-2 focus-visible:outline-ring">
            <span aria-hidden="true" className="text-base" style={{ color: nodeVisuals[type].color }}>{nodeVisuals[type].icon}</span><span>{t(`workflowEditor.types.${type}`)}</span>
          </button>)}</div>
        </aside>
        <Canvas state={state} onPositionChange={positions} onSelectionChange={selection} onConnect={connect} onDeleteSelection={deleteSelection} />
        <PropertiesPanel state={state} onUpdate={updateNodeField} errors={validation?.nodeErrors} sheetOpen={propertiesOpen} />
      </div>
    )}
    {saveError && <div className="p-4"><KosmoErrorAlert error={saveError} /></div>}
    {publishError && <div className="p-4"><KosmoErrorAlert error={publishError} /></div>}
    {activateError && <div className="p-4"><KosmoErrorAlert error={activateError} /></div>}
    {publishBlocked && validation?.level === "error" && (
      <div className="p-4">
        <div role="alert" data-testid="publish-blocked" className="rounded-md border border-destructive/50 bg-destructive/5 p-4 text-sm text-destructive">
          <p>{t("workflowEditor.publishBlocked" as never)}</p>
          <ul className="mt-2 list-disc space-y-1 pl-5">
            {[...validation.globalErrors, ...Object.values(validation.nodeErrors).flat()].map((message, index) => <li key={index}>{message}</li>)}
          </ul>
        </div>
      </div>
    )}
    {validationIssues.length > 0 && <div className="p-4"><KosmoErrorAlert error={{ code: "VALIDATION_FAILED", message_key: "errors.workflow.invalid", details: validationIssues }} /></div>}
    {notices.length > 0 && <div className="p-4 space-y-2">
      {notices.map((notice, index) => (
        <p key={`${notice.key}-${index}`} role="status" data-testid="editor-notice" data-key={notice.key} data-version={notice.version} className="text-sm text-muted-foreground">
          {String(notice.version === undefined ? t(notice.key as never) : t(notice.key as never, { version: notice.version } as never))}
        </p>
      ))}
    </div>}
    {selectedPosition && <output className="sr-only" aria-label={t("workflowEditor.selectedPosition")}>{selectedPosition}</output>}
    <div className="sr-only" aria-live="polite">{t("workflowEditor.connectionCount", { count: state?.definition.edges.length ?? 0 })}</div>
    <span className="sr-only" data-testid="connection-count">{t("workflowEditor.connectionCount", { count: state?.definition.edges.length ?? 0 })}</span>
    <ActivateDialog
      open={activateDialogOpen}
      onOpenChange={(open) => { if (!open) setActivateDialogOpen(false); }}
      candidates={activateCandidates}
      versionId={activateDefaultId}
      loading={activating}
      onConfirm={(versionId) => void runActivate(versionId, false)}
    />
    {confirmation && confirmationText && <ConfirmDialog
      open
      onOpenChange={(open) => { if (!open) setPendingConfirmation(null); }}
      title={String(t(confirmationText.title as never))}
      description={String(t(confirmationText.description as never))}
      confirmLabel={String(t(confirmationText.confirmLabel as never))}
      cancelLabel={t("common.cancel")}
      loading={busy}
      onConfirm={() => {
        const kind = confirmation.kind;
        const confirmedVersionId = confirmation.versionId ?? null;
        setPendingConfirmation(null);
        if (kind === "activate-stale-base" && confirmedVersionId) void runActivate(confirmedVersionId, true);
        else void runPublish(true);
      }}
    />}
  </main>;
}

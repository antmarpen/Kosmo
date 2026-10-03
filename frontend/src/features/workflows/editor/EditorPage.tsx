import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useNavigate, useParams, useSearchParams } from "react-router";
import { useTranslation } from "react-i18next";
import { api } from "@/api/auth";
import { toKosmoError as normalizeKosmoError, unwrap } from "@/api/apiError";
import { Button } from "@/components/ui/button";
import { ConfirmDialog } from "@/components/ConfirmDialog";
import { Input } from "@/components/ui/input";
import { KosmoErrorAlert, type KosmoError } from "@/components/KosmoErrorAlert";
import { Canvas, NODE_DRAG_MIME, nodeVisuals } from "./Canvas";
import { ActivateDialog, type PublishedVersionChoice } from "./ActivateDialog";
import { createNode, deleteEdge, deleteNode, deriveInputs, deserializeWorkflow, serializeWorkflow, updateNode, type WorkflowDefinition, type WorkflowEdge, type WorkflowEditorState, type WorkflowNode } from "./model";
import { PropertiesPanel } from "./PropertiesPanel";
import { locateServerIssues, validateWorkflow, type ValidationIssue } from "./validation";
import type { components } from "@/api/schema";

type DraftResponse = components["schemas"]["WorkflowDraftResponse"];
type DraftMetadata = components["schemas"]["WorkflowDraftMetadata"];
type CreatedDraft = { draft_id: string; revision: number };
type SaveDraftResponse = { revision: number; issues?: KosmoError["details"] };
type PublishVersionResponse = components["schemas"]["WorkflowVersionResponse"];
type WorkflowVersionSummary = components["schemas"]["WorkflowVersionSummary"];
/** Contract of POST /workflows/{workflow_id}/activate (route has no response_model). */
type ActivatedVersion = { version_id: string; active_revision: number };
/**
 * WorkflowResponse plus `publication_revision`. The generated client does not
 * expose the field yet (schema.d.ts is coordinator-owned); the backend already
 * returns it once the list/detail services are updated.
 */
type WorkflowInfo = components["schemas"]["WorkflowResponse"] & { publication_revision: number };
type EditorNoticeKey = "workflowEditor.publishSuccess" | "workflowEditor.publishWorkflowChanged" | "workflowEditor.activateSuccess";
type EditorNotice = { key: EditorNoticeKey; version?: number };
type PendingConfirmation = { kind: "publish-recent" | "publish-stale-base" | "activate-stale-base"; versionId?: string };

const types: WorkflowNode["type"][] = ["script", "ai", "http", "decision", "workflow"];

/** Page size the activation picker requests from the versions listing (backend default, 1..100). */
const VERSIONS_PAGE_SIZE = 50;

/**
 * English fallbacks for the pending `workflowEditor.typeDescriptions.*` catalog
 * keys (same transitional contract as the wizard's edit-mode keys): the catalog
 * value wins once the coordinator lands the keys, this fallback keeps the UI
 * honest until then.
 */
const TYPE_DESCRIPTIONS: Record<WorkflowNode["type"], string> = {
  start: "Entry point of the workflow.",
  script: "Run a Python script in an isolated sandbox.",
  ai: "Delegate a step to an AI agent.",
  http: "Call an HTTP endpoint and collect its response.",
  decision: "Branch the flow to one of the outgoing connections.",
  workflow: "Invoke another workflow as a step.",
  end: "Final node of the workflow.",
};

/** Normalizes failures with the editor fallback code (shared contract in @/api/apiError). */
function toKosmoError(cause: unknown): KosmoError {
  return normalizeKosmoError(cause, "WORKFLOW_EDITOR_FAILED");
}

function nodeId() { return `node-${globalThis.crypto?.randomUUID?.() ?? `${Date.now()}-${Math.random().toString(36).slice(2)}`}`; }

/** Blank authoring seed used when a draft has no usable definition yet. */
function blankDefinition(name?: string): WorkflowDefinition {
  return { schema_version: "v1", name: name ?? "Untitled workflow", nodes: [createNode("start", "start"), createNode("end", "end")], edges: [] };
}

/**
 * Draft definitions come from the API as opaque JSON. A draft seeded before
 * its workflow had any published version is `{}`; treat anything without a v1
 * node list as an empty graph and fall back to the blank editor seed. The
 * blank seed takes the workflow's own name, so a created workflow opens
 * showing the name it was created with instead of a placeholder that
 * publishing would silently rename the workflow to.
 */
function toEditorState(definition: unknown, layout: unknown, workflowName?: string): WorkflowEditorState {
  const candidate = definition as Partial<WorkflowDefinition> | null;
  const usable = !!candidate && candidate.schema_version === "v1" && typeof candidate.name === "string"
    && Array.isArray(candidate.nodes) && candidate.nodes.length > 0 && Array.isArray(candidate.edges);
  const typedLayout = layout && typeof layout === "object" ? (layout as WorkflowEditorState["layout"]) : undefined;
  return deserializeWorkflow(usable ? (candidate as WorkflowDefinition) : blankDefinition(workflowName), typedLayout);
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

/** Loads the workflow resource (WorkflowResponse plus `publication_revision`). */
async function fetchWorkflowInfo(workflowId: string): Promise<WorkflowInfo> {
  return unwrap(await api.GET("/workflows/{workflow_id}", { params: { path: { workflow_id: workflowId } } })) as WorkflowInfo;
}

/** Everything the editor needs to open: the draft to load and the workflow's name for the blank seed. */
async function resolveEditorBootstrap(workflowId: string, requestedDraftId?: string): Promise<{ draft: DraftResponse; workflowName: string }> {
  const [draft, workflow] = await Promise.all([resolveDraft(workflowId, requestedDraftId), fetchWorkflowInfo(workflowId)]);
  return { draft, workflowName: workflow.name };
}

export function EditorPage() {
  const { t, i18n } = useTranslation();
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
  const [validationIssues, setValidationIssues] = useState<NonNullable<KosmoError["details"]>>([]);
  const [analysisIssues, setAnalysisIssues] = useState<Record<string, ValidationIssue[]>>({});
  const [saving, setSaving] = useState(false);
  const [dirty, setDirty] = useState(false);
  const [paletteOpen, setPaletteOpen] = useState(false);
  const [propertiesOpen, setPropertiesOpen] = useState(false);
  const [typeQuery, setTypeQuery] = useState("");
  const [counter, setCounter] = useState(0);
  // Publication state: fetchWorkflow returns the workflow resource on demand
  // (publish precondition: publication_revision; activation precondition:
  // active_version); the published-version listing feeds the picker. Pages
  // accumulate so "load more" reaches versions beyond the first page.
  const [lastPublishedVersion, setLastPublishedVersion] = useState<PublishedVersionChoice | null>(null);
  // Every published version loaded so far (server listing), so the picker keeps
  // offering previously published inactive versions after a reload.
  const [publishedVersions, setPublishedVersions] = useState<WorkflowVersionSummary[]>([]);
  // True once a page came back short: no further versions exist server-side.
  const [versionsComplete, setVersionsComplete] = useState(true);
  const [loadingMoreVersions, setLoadingMoreVersions] = useState(false);
  // Spec AC-P2-06: the save/publish flow offers activation, off by default.
  const [activateAfterPublish, setActivateAfterPublish] = useState(false);
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
  const loadRef = useRef<{ key: string; promise: Promise<{ draft: DraftResponse; workflowName: string }> } | null>(null);
  const scriptAnalysis = useRef(new Map<string, string>());

  // Analyze scripts against their exact source and derived inputs. A settled
  // response is accepted only while that same key is still current.
  useEffect(() => {
    if (!state) return;
    for (const node of state.definition.nodes) {
      if (node.type !== "script") continue;
      const key = JSON.stringify([node.code, node.inputs]);
      if (scriptAnalysis.current.get(node.id) === key || scriptAnalysis.current.get(node.id) === `${key}:pending` || scriptAnalysis.current.get(node.id) === `${key}:failed`) continue;
      scriptAnalysis.current.set(node.id, `${key}:pending`);
      void api.POST("/workflows/script-analysis", { body: { code: node.code, inputs: node.inputs } }).then((response) => {
        const result = unwrap(response) as { outputs: string[]; issues: unknown[] };
        if (!result || !Array.isArray(result.outputs) || !Array.isArray(result.issues)) throw new Error("Invalid script analysis response");
        if (scriptAnalysis.current.get(node.id) !== key) return;
        setAnalysisIssues((current) => ({ ...current, [node.id]: (result.issues as { message_key: string; params?: Record<string, unknown> }[]).map((issue) => ({ message_key: issue.message_key, params: issue.params })) }));
        setState((current) => current ? { ...current, definition: { ...current.definition, nodes: current.definition.nodes.map((candidate) => candidate.id === node.id && candidate.type === "script" && JSON.stringify([candidate.code, candidate.inputs]) === key ? { ...candidate, outputs: result.issues.length ? [] : result.outputs } : candidate) } } : current);
      }).catch(() => {
        if (scriptAnalysis.current.get(node.id) === key) {
          scriptAnalysis.current.set(node.id, `${key}:failed`);
          setAnalysisIssues((current) => ({ ...current, [node.id]: [{ message_key: "workflowEditor.validation.scriptAnalysisFailed" }] }));
        }
      });
    }
    for (const id of scriptAnalysis.current.keys()) if (!state.definition.nodes.some((node) => node.id === id)) scriptAnalysis.current.delete(id);
  }, [state]);

  useEffect(() => {
    if (!id) {
      setLoadError({ code: "WORKFLOW_EDITOR_FAILED", message_key: "errors.workflow.not_found" });
      setStatus("error");
      return;
    }
    if (loadRef.current?.key !== id) loadRef.current = { key: id, promise: resolveEditorBootstrap(id, requestedDraftIdRef.current) };
    let active = true;
    loadRef.current.promise.then((bootstrap) => {
      if (!active) return;
      setState(toEditorState(bootstrap.draft.definition, bootstrap.draft.layout, bootstrap.workflowName));
      setDraftId(bootstrap.draft.id);
      setRevision(bootstrap.draft.revision);
      setStatus("ready");
      setLoadError(null);
      if (!requestedDraftIdRef.current) navigate(`/workflows/${id}/edit?draftId=${encodeURIComponent(bootstrap.draft.id)}`, { replace: true });
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
    // sheet is never covered. Clearing the selection (canvas pane click)
    // closes the sheet again — the panel only exists with a selection.
    if (nodeIds.length) { setPaletteOpen(false); setPropertiesOpen(true); }
    else setPropertiesOpen(false);
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
      ? deriveInputs({ ...current, definition: { ...current.definition, edges: [...current.definition.edges, edge] } })
      : current);
    setDirty(true);
  }, []);
  const addNode = (type: WorkflowNode["type"], position?: { x: number; y: number }) => {
    if (type === "start" || type === "end") return;
    const newId = nodeId();
    setCounter((number) => number + 1);
    setState((current) => current ? { ...current, definition: { ...current.definition, nodes: [...current.definition.nodes, createNode(type, newId)] }, layout: { ...current.layout, positions: { ...current.layout.positions, [newId]: position ?? { x: 100 + current.definition.nodes.length * 28, y: 90 + counter * 20 } } }, selection: { nodeIds: [newId] } } : current);
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
    // Whatever the panel was showing is gone now (deleteNode clears the
    // deleted ids from the selection), so the sheet state follows.
    setPropertiesOpen(false);
  }, []);
  const updateNodeField = useCallback((nodeIdValue: string, patch: Partial<WorkflowNode>) => {
    setState((current) => current ? updateNode(current, nodeIdValue, patch) : current);
    setDirty(true);
  }, []);
  // The workflow name lives on the definition: editing it marks the draft
  // dirty, and the next save persists it. Publication renames the workflow
  // itself (backend contract), so the list always matches the published name.
  const renameWorkflow = useCallback((name: string) => {
    setState((current) => current ? { ...current, definition: { ...current.definition, name } } : current);
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

  /** Loads the workflow resource on demand; throws the flat KosmoError body on failure. */
  const fetchWorkflow = useCallback(async (): Promise<WorkflowInfo | null> => {
    if (!id) return null;
    return unwrap(await api.GET("/workflows/{workflow_id}", { params: { path: { workflow_id: id } } })) as WorkflowInfo;
  }, [id]);

  /** Loads one page of the published-version listing (metadata only, newest first) that feeds the activation picker. */
  const fetchVersions = useCallback(async (offset: number): Promise<WorkflowVersionSummary[]> => {
    if (!id) return [];
    return ((unwrap(await api.GET("/workflows/{workflow_id}/versions", {
      params: { path: { workflow_id: id }, query: { limit: VERSIONS_PAGE_SIZE, offset } },
    })) as WorkflowVersionSummary[] | null) ?? []);
  }, [id]);

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

  /**
   * Publishes the saved draft as a new version. Publishing never activates on
   * its own; when the (default-off) activate option is checked, the version
   * just published is activated through the same explicit, confirmed request
   * path as the picker. Optimistic-revision conflicts adopt the returned
   * revision and retry once; the recent-publication and stale-base conflicts
   * require explicit confirmation, so the flow pauses and resends with
   * `confirm_overwrite`.
   */
  const runPublish = useCallback(async (confirmOverwrite: boolean) => {
    const current = stateRef.current;
    if (!id || !draftId || !current || publishing) return;
    if (current.definition.nodes.some((node) => node.type === "script" && scriptAnalysis.current.get(node.id) !== JSON.stringify([node.code, node.inputs]))) {
      setPublishBlocked(true);
      return;
    }
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
    setValidationIssues([]);
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
      if (activateAfterPublish) await runActivate(result.id, false);
    } catch (cause) {
      const error = toKosmoError(cause);
      // A server-side validation rejection carries locatable issue details;
      // map them onto the nodes the same way the save response does.
      if (error.code === "VALIDATION_FAILED" && error.details?.length) setValidationIssues(error.details);
      setPublishError(error);
    } finally {
      setPublishing(false);
    }
  }, [activateAfterPublish, dirty, draftId, fetchWorkflow, id, publishing, runActivate, saveDraft]);

  /** Opens the activation picker with the freshest workflow and first version page. */
  const openActivate = useCallback(async () => {
    if (!id || activating) return;
    setActivateError(null);
    try {
      const [, firstPage] = await Promise.all([fetchWorkflow(), fetchVersions(0)]);
      setPublishedVersions(firstPage);
      setVersionsComplete(firstPage.length < VERSIONS_PAGE_SIZE);
      setActivateDialogOpen(true);
    } catch (cause) {
      setActivateError(toKosmoError(cause));
    }
  }, [activating, fetchVersions, fetchWorkflow, id]);

  /** Appends the next version page so versions beyond the first page stay reachable in the picker. */
  const loadMoreVersions = useCallback(async () => {
    if (!id || loadingMoreVersions) return;
    setLoadingMoreVersions(true);
    try {
      const nextPage = await fetchVersions(publishedVersions.length);
      setPublishedVersions((current) => [...current, ...nextPage]);
      setVersionsComplete(nextPage.length < VERSIONS_PAGE_SIZE);
    } catch (cause) {
      setActivateError(toKosmoError(cause));
    } finally {
      setLoadingMoreVersions(false);
    }
  }, [fetchVersions, id, loadingMoreVersions, publishedVersions.length]);

  const selectedPosition = useMemo(() => {
    if (!state) return "";
    const selectedId = state.selection.nodeIds[0];
    const position = selectedId ? state.layout.positions[selectedId] : undefined;
    return position ? `${position.x}, ${position.y}` : "";
  }, [state]);

  const validation = useMemo(() => (state ? validateWorkflow(state) : null), [state]);

  /** Renders a validation issue through the catalogs; pending keys show their dotted path until the coordinator lands them. */
  const translateIssue = useCallback((issue: ValidationIssue) => String(i18n.exists(issue.message_key)
    ? t(issue.message_key as never, (issue.params ?? {}) as never)
    : issue.message_key), [i18n, t]);

  // Server draft-validation issues from the last save/publish: located issues
  // join the client-side node errors on the properties panel; the rest stay in
  // the summary alert.
  const serverIssues = useMemo(
    () => locateServerIssues(validationIssues, state?.definition.nodes ?? []),
    [state, validationIssues],
  );
  const nodeErrorMessages = useMemo(() => {
    const messages: Record<string, string[]> = {};
    const add = (nodeId: string, issue: ValidationIssue) => { (messages[nodeId] ??= []).push(translateIssue(issue)); };
    for (const [nodeId, issues] of Object.entries(validation?.nodeErrors ?? {})) for (const issue of issues) add(nodeId, issue);
    for (const [nodeId, issues] of Object.entries(serverIssues.nodeErrors)) for (const issue of issues) add(nodeId, issue);
    for (const [nodeId, issues] of Object.entries(analysisIssues)) for (const issue of issues) add(nodeId, issue);
    return messages;
  }, [analysisIssues, serverIssues, translateIssue, validation]);

  // Activation choices come from the server listing (newest first), so every
  // published version stays selectable after a reload; the just-published one
  // is included as soon as the dialog is opened.
  const activateCandidates = useMemo<PublishedVersionChoice[]>(
    () => publishedVersions.map(({ id, version, is_active }) => ({ id, version, is_active })),
    [publishedVersions],
  );
  const activateDefaultId = lastPublishedVersion?.id
    ?? activateCandidates.find((candidate) => candidate.is_active)?.id
    // After a reload there is no just-published version and possibly no active
    // one; default to the newest available candidate so the picker is operable
    // through ordinary interaction instead of holding a disabled confirm.
    ?? activateCandidates[0]?.id
    ?? null;

  const confirmation = pendingConfirmation;
  const confirmationText: { title: "workflowEditor.confirmRecentPublicationTitle" | "workflowEditor.confirmStaleBasePublishTitle" | "workflowEditor.confirmStaleBaseActivateTitle"; description: "workflowEditor.confirmRecentPublicationDescription" | "workflowEditor.confirmStaleBasePublishDescription" | "workflowEditor.confirmStaleBaseActivateDescription"; confirmLabel: "workflowEditor.publishAnyway" | "workflowEditor.activateAnyway" } | null = confirmation === null ? null : confirmation.kind === "publish-recent"
    ? { title: "workflowEditor.confirmRecentPublicationTitle", description: "workflowEditor.confirmRecentPublicationDescription", confirmLabel: "workflowEditor.publishAnyway" }
    : confirmation.kind === "publish-stale-base"
      ? { title: "workflowEditor.confirmStaleBasePublishTitle", description: "workflowEditor.confirmStaleBasePublishDescription", confirmLabel: "workflowEditor.publishAnyway" }
      : { title: "workflowEditor.confirmStaleBaseActivateTitle", description: "workflowEditor.confirmStaleBaseActivateDescription", confirmLabel: "workflowEditor.activateAnyway" };

  const ready = status === "ready" && state !== null;
  const busy = publishing || activating;

  // The properties panel exists only for a real selected node: a stale
  // selection id (a just-deleted node) hides the panel like no selection.
  const selectedNode = useMemo(() => {
    if (!state) return null;
    const selectedId = state.selection.nodeIds[0];
    return selectedId ? state.definition.nodes.find((node) => node.id === selectedId) ?? null : null;
  }, [state]);
  // Catalog entries filtered by the palette search: the localized type name
  // and its (pending-key) description are both searchable.
  const paletteDescription = useCallback((type: WorkflowNode["type"]) =>
    String(t(`workflowEditor.typeDescriptions.${type}` as never, { defaultValue: TYPE_DESCRIPTIONS[type] })), [t]);
  const visibleTypes = useMemo(() => {
    const query = typeQuery.trim().toLowerCase();
    if (!query) return types;
    return types.filter((type) =>
      t(`workflowEditor.types.${type}`).toLowerCase().includes(query)
      || paletteDescription(type).toLowerCase().includes(query));
  }, [paletteDescription, t, typeQuery]);

  // The editor fills exactly the viewport minus the shell header. The explicit
  // height must stay authoritative: as a flex-1 item inside the shell's
  // content-sized chain, this element (and with it the canvas React Flow
  // measures) grew with the tallest properties panel's content, which pushed
  // every node handle below the fold after fitView and silently broke pointer
  // connections (0 edges in the phase-2 authoring journeys).
  return <main className="flex h-[calc(100dvh-3.5rem)] min-h-0 shrink-0 flex-col overflow-hidden">
    <header className="flex flex-wrap items-center justify-between gap-3 border-b border-border bg-background px-4 py-3 sm:px-6">
      <div className="flex min-w-0 flex-wrap items-center gap-3">
        <h1 className="text-lg font-semibold">{t("workflowEditor.title")}</h1>
        {ready && <Input
          aria-label={t("workflowEditor.nameLabel")}
          value={state.definition.name}
          onChange={(event) => renameWorkflow(event.target.value)}
          autoComplete="off"
          maxLength={200}
          className="h-8 w-44 sm:w-64"
        />}
        <span className="hidden text-xs text-muted-foreground sm:inline">{t("workflowEditor.nodeCount", { count: state?.definition.nodes.length ?? 0 })}</span>{revision !== null && <span className="hidden text-xs text-muted-foreground sm:inline">{t("workflowEditor.revision", { revision })}</span>}
      </div>
      <div className="flex flex-wrap items-center justify-end gap-2">
        {ready && <span role="status" className="text-xs text-muted-foreground">{saving ? t("workflowEditor.saving") : dirty ? t("workflowEditor.unsaved") : t("workflowEditor.saved")}</span>}
        <Button variant="outline" className="lg:hidden" aria-expanded={paletteOpen} onClick={() => { setPropertiesOpen(false); setPaletteOpen((open) => !open); }}>{t("workflowEditor.addNode")}</Button>
        <Button variant="outline" className="lg:hidden" aria-expanded={propertiesOpen} disabled={!selectedNode} onClick={() => { setPaletteOpen(false); setPropertiesOpen((open) => !open); }}>{t("editor.properties")}</Button>
          {ready && (!selectedNode || (selectedNode.type !== "start" && selectedNode.type !== "end")) && <Button variant="outline" onClick={deleteSelection}>{t("workflowEditor.deleteSelection")}</Button>}
        {/* Spec AC-P2-06: optional activation in the publish flow, off by default. */}
        {ready && <label className="flex items-center gap-1.5 text-xs text-muted-foreground">
          <input
            type="checkbox"
            className="size-4 accent-primary"
            checked={activateAfterPublish}
            disabled={busy}
            onChange={(event) => setActivateAfterPublish(event.target.checked)}
          />
          {t("workflowEditor.activateAfterPublish" as never)}
        </label>}
        <Button variant="outline" disabled={!ready || busy} loading={publishing} onClick={() => void runPublish(false)}>{t("workflowEditor.publish")}</Button>
        <Button variant="outline" disabled={!ready || busy} loading={activating} onClick={() => void openActivate()}>{t("workflowEditor.activate")}</Button>
        <Button disabled={!ready || saving || busy} loading={saving} onClick={() => void saveDraft()}>{t("workflowEditor.saveDraft")}</Button>
      </div>
    </header>
    {/* Side-by-side panels only once they actually fit next to the shell
        sidebar (lg): at md the three fixed columns left the canvas 0px wide. */}
    {status === "loading" ? <p role="status" className="p-6 text-sm text-muted-foreground">{t("workflowEditor.loading")}</p> : status === "error" || !state ? <div className="p-6"><KosmoErrorAlert error={loadError ?? { code: "WORKFLOW_EDITOR_FAILED", message_key: "errors.generic" }} /></div> : (
      <div className="flex min-h-0 flex-1 flex-col lg:flex-row">
        <aside aria-label={t("workflowEditor.palette")} className={`${paletteOpen ? "fixed inset-x-0 bottom-0 z-20 max-h-[65vh] rounded-t-lg border-t bg-background shadow-lg" : "hidden"} w-full overflow-y-auto p-4 lg:static lg:block lg:w-56 lg:shrink-0 lg:border-r lg:border-t-0 lg:rounded-none lg:shadow-none`}>
          <h2 className="mb-3 text-sm font-semibold">{t("workflowEditor.palette")}</h2>
          <Input
            type="search"
            value={typeQuery}
            onChange={(event) => setTypeQuery(event.target.value)}
            placeholder={t("workflowEditor.paletteSearch" as never, { defaultValue: "Search node types" })}
            aria-label={t("workflowEditor.paletteSearch" as never, { defaultValue: "Search node types" })}
            className="mb-3"
          />
          {visibleTypes.length === 0 ? <p className="text-sm text-muted-foreground">{t("workflowEditor.paletteNoResults" as never, { defaultValue: "No node types match \u201C{{query}}\u201D.", query: typeQuery.trim() })}</p> : (
            <div className="grid grid-cols-2 gap-2 lg:grid-cols-1">{visibleTypes.map((type) => (
              <button
                key={type}
                type="button"
                draggable
                onDragStart={(event) => {
                  event.dataTransfer.setData(NODE_DRAG_MIME, type);
                  event.dataTransfer.effectAllowed = "copy";
                }}
                aria-label={t("workflowEditor.addType", { type: t(`workflowEditor.types.${type}`) })}
                onClick={() => addNode(type)}
                className="flex min-h-10 items-center gap-3 rounded-md border border-border bg-background px-3 py-2 text-left text-sm hover:bg-muted focus-visible:outline-2 focus-visible:outline-ring"
              >
                <span aria-hidden="true" className="text-base" style={{ color: nodeVisuals[type].color }}>{nodeVisuals[type].icon}</span>
                <span className="min-w-0">
                  <span className="block truncate font-medium">{t(`workflowEditor.types.${type}`)}</span>
                  <span className="block text-xs font-normal leading-4 text-muted-foreground">{paletteDescription(type)}</span>
                  {type === "decision" && <span className="block text-xs font-medium text-amber-700 dark:text-amber-400">{t("editor.decisionNotFunctional" as never)}</span>}
                </span>
              </button>
            ))}</div>
          )}
        </aside>
        <Canvas state={state} onPositionChange={positions} onSelectionChange={selection} onConnect={connect} onDeleteSelection={deleteSelection} onDropNode={addNode} />
        <PropertiesPanel state={state} onUpdate={updateNodeField} errors={nodeErrorMessages} sheetOpen={propertiesOpen} />
      </div>
    )}
    {saveError && <div className="p-4"><KosmoErrorAlert error={saveError} /></div>}
    {publishError && <div className="p-4"><KosmoErrorAlert error={publishError} /></div>}
    {activateError && <div className="p-4"><KosmoErrorAlert error={activateError} /></div>}
    {publishBlocked && validation?.level === "error" && (
      <div className="p-4">
        <div role="alert" data-testid="publish-blocked" className="rounded-md border border-destructive/50 bg-destructive/5 p-4 text-sm text-destructive">
          <p>{t("workflowEditor.publishBlocked")}</p>
          <ul className="mt-2 list-disc space-y-1 pl-5">
            {[...validation.globalErrors, ...Object.values(validation.nodeErrors).flat()].map((issue, index) => <li key={index}>{translateIssue(issue)}</li>)}
          </ul>
        </div>
      </div>
    )}
    {serverIssues.globalErrors.length > 0 && <div className="p-4"><KosmoErrorAlert error={{ code: "VALIDATION_FAILED", message_key: "errors.workflow.invalid", details: serverIssues.globalErrors }} /></div>}
    {notices.length > 0 && <div className="p-4 space-y-2">
      {notices.map((notice, index) => (
        <p key={`${notice.key}-${index}`} role="status" data-testid="editor-notice" data-key={notice.key} data-version={notice.version} className="text-sm text-muted-foreground">
          {notice.version === undefined ? t(notice.key) : t(notice.key, { version: notice.version })}
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
      hasMore={!versionsComplete}
      loadingMore={loadingMoreVersions}
      onLoadMore={() => void loadMoreVersions()}
      onConfirm={(versionId) => void runActivate(versionId, false)}
    />
    {confirmation && confirmationText && <ConfirmDialog
      open
      onOpenChange={(open) => { if (!open) setPendingConfirmation(null); }}
      title={String(t(confirmationText.title))}
      description={String(t(confirmationText.description))}
      confirmLabel={String(t(confirmationText.confirmLabel))}
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

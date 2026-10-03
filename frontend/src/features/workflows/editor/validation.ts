import type { KosmoErrorDetail } from "@/components/KosmoErrorAlert";
import type { WorkflowEditorState, WorkflowNode } from "./model";

/**
 * A localized validation issue: a catalog message key plus interpolation
 * params. Location is carried by the container — node-located issues live in
 * `nodeErrors` keyed by node id, graph-level ones in `globalErrors`.
 */
export type ValidationIssue = { message_key: string; params?: Record<string, unknown> };
export type ValidationResult = { level: "valid" | "warning" | "error"; nodeErrors: Record<string, ValidationIssue[]>; globalErrors: ValidationIssue[] };

/** Mirrors the backend SafeIdentifier pattern (backend/shared/graph/schema.py). */
const SAFE_IDENTIFIER = /^[a-zA-Z0-9._-]{1,64}$/;

/** Coerces authoring values to strings so validation stays total: an opaque
 * server-loaded draft can carry mistyped values that the JSON paste controls
 * would reject, and a localized issue must surface instead of a TypeError. */
const str = (value: unknown) => (typeof value === "string" ? value : "");

/** Reads a possibly-broken entry as an object (primitives/null degrade to an empty record). */
const record = (value: unknown): Record<string, unknown> => (typeof value === "object" && value !== null ? value as Record<string, unknown> : {});

/** Reads a possibly-broken declared list (inputs/outputs) as an array. */
const strings = (value: unknown): unknown[] => (Array.isArray(value) ? value : []);

export function validateWorkflow(state: WorkflowEditorState): ValidationResult {
  const nodes = strings(state.definition.nodes) as WorkflowNode[];
  const edges = strings(state.definition.edges);
  const nodeErrors: Record<string, ValidationIssue[]> = {};
  const globalErrors: ValidationIssue[] = [];
  const add = (id: string, issue: ValidationIssue) => { (nodeErrors[id] ??= []).push(issue); };
  const starts = nodes.filter((node) => node.type === "start");
  if (!starts.length) globalErrors.push({ message_key: "workflowEditor.validation.startRequired" });
  const ends = nodes.filter((node) => node.type === "end");
  if (!ends.length) globalErrors.push({ message_key: "workflowEditor.validation.endRequired" });
  const ids = new Set<string>();
  const byId = new Map(nodes.map((node) => [node.id, node]));
  for (const node of nodes) {
    const producers = new Set<string>();
    for (const raw of edges) {
      const edge = record(raw);
      if (edge.to !== node.id) continue;
      const source = byId.get(str(edge.from));
      const outputs = source?.type === "start" ? source.input_form.map((field) => field.name) : source && "outputs" in source ? source.outputs : [];
      for (const name of outputs) {
        if (producers.has(name)) { add(node.id, { message_key: "workflowEditor.validation.duplicateProducer" }); break; }
        producers.add(name);
      }
      if (nodeErrors[node.id]?.some((issue) => issue.message_key === "workflowEditor.validation.duplicateProducer")) break;
    }
  }
  for (const node of nodes) {
    if (ids.has(node.id)) add(node.id, { message_key: "workflowEditor.validation.duplicateNodeId" });
    ids.add(node.id);
    validateNode(node, add);
  }
  if (starts.length) {
    const adjacency = new Map(nodes.map((node) => [node.id, [] as string[]]));
    for (const raw of edges) { const edge = record(raw); adjacency.get(str(edge.from))?.push(str(edge.to)); }
    const reached = new Set<string>(), pending = [starts[0].id];
    while (pending.length) { const id = pending.pop()!; if (reached.has(id)) continue; reached.add(id); pending.push(...(adjacency.get(id) ?? [])); }
    for (const node of nodes) if (!reached.has(node.id)) add(node.id, { message_key: "workflowEditor.validation.unreachable" });
    if (ends.length && !ends.some((node) => reached.has(node.id))) globalErrors.push({ message_key: "workflowEditor.validation.noReachableEnd" });
  }
  const hasNodeErrors = Object.keys(nodeErrors).length > 0;
  return { level: globalErrors.length || hasNodeErrors ? "error" : "valid", nodeErrors, globalErrors };
}

function validateIdentifiers(node: WorkflowNode, values: unknown[], kind: string, add: (id: string, issue: ValidationIssue) => void) {
  values.forEach((value, index) => {
    const text = str(value);
    if (!text.trim()) add(node.id, { message_key: `workflowEditor.validation.${kind}Empty`, params: { index: index + 1 } });
    else if (!SAFE_IDENTIFIER.test(text)) add(node.id, { message_key: `workflowEditor.validation.${kind}Invalid`, params: { index: index + 1 } });
  });
}

function validateNode(node: WorkflowNode, add: (id: string, issue: ValidationIssue) => void) {
  switch (node.type) {
    case "start": {
      // input_form is typed FormField[], but a raw draft may carry anything.
      const form: unknown[] = Array.isArray(node.input_form) ? node.input_form : [];
      form.forEach((raw, index) => {
        const field = record(raw);
        const name = str(field.name);
        if (!name.trim()) add(node.id, { message_key: "workflowEditor.validation.startFieldNameRequired", params: { index: index + 1 } });
        else if (!SAFE_IDENTIFIER.test(name)) add(node.id, { message_key: "workflowEditor.validation.startFieldNameInvalid", params: { index: index + 1 } });
      });
      break;
    }
    case "script":
      if (!str(node.code).trim()) add(node.id, { message_key: "workflowEditor.validation.codeRequired" });
      validateIdentifiers(node, strings(node.inputs), "input", add);
      validateIdentifiers(node, strings(node.outputs), "output", add);
      validateOutputContracts(node, node.outputs, add);
      break;
    case "http":
      if (!str(node.method).trim()) add(node.id, { message_key: "workflowEditor.validation.methodRequired" });
      if (!str(node.url).trim()) add(node.id, { message_key: "workflowEditor.validation.urlRequired" });
      if (JSON.stringify(node.outputs) !== '["response"]') add(node.id, { message_key: "workflowEditor.validation.httpOutputFixed" });
      validateOutputContracts(node, node.outputs, add);
      break;
    case "ai": {
      if (!str(record(node.agent).model).trim()) add(node.id, { message_key: "workflowEditor.validation.modelRequired" });
      if (!str(node.prompt_template).trim()) add(node.id, { message_key: "workflowEditor.validation.promptRequired" });
      validateIdentifiers(node, strings(node.inputs), "input", add);
      validateIdentifiers(node, strings(node.outputs), "output", add);
      validateOutputContracts(node, node.outputs, add);
      break;
    }
    case "workflow":
      if (!str(node.workflow_id).trim()) add(node.id, { message_key: "workflowEditor.validation.workflowRefRequired" });
      validateOutputContracts(node, [], add);
      break;
    case "decision": if (!str(node.selected_next_node_id).trim()) add(node.id, { message_key: "workflowEditor.validation.routeRequired" }); break;
  }
}

/**
 * Locates server draft-validation issues on the editor graph. Issues naming a
 * node through `params.node_id` or a definition field path
 * (`params.field = "nodes.<index>…"` ) attach to that node; anything else
 * stays in the summary. Preserves the message key and params so the caller
 * renders them through the catalogs.
 */
export function locateServerIssues(details: KosmoErrorDetail[] | undefined, nodes: WorkflowNode[]): { nodeErrors: Record<string, ValidationIssue[]>; globalErrors: ValidationIssue[] } {
  const nodeErrors: Record<string, ValidationIssue[]> = {};
  const globalErrors: ValidationIssue[] = [];
  const nodeAtField = (field: unknown) => {
    const match = typeof field === "string" ? /^nodes\.(\d+)/.exec(field) : null;
    const index = match ? Number(match[1]) : -1;
    return index >= 0 && index < nodes.length ? nodes[index].id : null;
  };
  for (const detail of details ?? []) {
    const issue: ValidationIssue = { message_key: detail.message_key, params: detail.params };
    const nodeId = typeof detail.params?.node_id === "string" ? detail.params.node_id : nodeAtField(detail.params?.field);
    if (nodeId && nodes.some((node) => node.id === nodeId)) (nodeErrors[nodeId] ??= []).push(issue);
    else globalErrors.push(issue);
  }
  return { nodeErrors, globalErrors };
}

function validateOutputContracts(node: WorkflowNode, outputs: string[], add: (id: string, issue: ValidationIssue) => void) {
  if (!("output_validation" in node) || !node.output_validation) return;
  for (const name of Object.keys(node.output_validation)) if (!outputs.includes(name)) add(node.id, { message_key: "workflowEditor.validation.orphanedOutputValidation", params: { output: name } });
}

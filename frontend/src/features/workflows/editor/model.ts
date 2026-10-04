import { createNode } from "./nodeDefaults";
import { deserializeWorkflow, serializeWorkflow } from "./serialization";
import { validateWorkflow } from "./validation";

/**
 * Authoring contract for workflow definitions, mirroring
 * backend/shared/graph/schema.py. These types previously came from the
 * generated API schema; the workflow definition is no longer an HTTP
 * transport type (creation takes only a name and drafts carry opaque JSON),
 * so the editor owns its authoring types locally.
 */
export type FormField = { name: string; type: "string" | "number" | "boolean"; required: boolean; validation?: ValidationContract | LegacyValidationContract };
export type StartNode = { type: "start"; id: string; input_form: FormField[] };
export type ScriptNode = { type: "script"; id: string; code: string; inputs: string[]; outputs: string[]; output_validation?: Record<string, ValidationContract> };
export type HttpNode = { type: "http"; id: string; method: string; url: string; inputs: string[]; outputs: ["response"]; output_validation?: Record<string, ValidationContract> };
export type ValidationContract = { format: "text" | "markdown" } | { format: "json"; json_schema?: boolean | Record<string, unknown> | null; rules_code?: string | null } | { format: "yaml"; rules_code?: string | null };
export type ValidationLevel = { name: string; message_key: string; params_schema: Record<string, unknown> };
export type LegacyValidationContract = { levels: ValidationLevel[] };
export type AiNode = { type: "ai"; id: string; agent_id?: string | null; model?: string; reasoning_effort?: string; added_mcp_ids?: string[]; removed_mcp_ids?: string[]; added_skill_ids?: string[]; removed_skill_ids?: string[]; prompt_template: string; inputs: string[]; outputs: string[]; output_validation?: Record<string, ValidationContract>; max_validation_cycles: number };
export type EndNode = { type: "end"; id: string; inputs: string[] };
export type DecisionNode = { type: "decision"; id: string; selected_next_node_id: string };
export type WorkflowNodeRef = { type: "workflow"; id: string; workflow_id: string; inputs: string[]; output_validation?: Record<string, ValidationContract> };
export type WorkflowNode = StartNode | ScriptNode | HttpNode | AiNode | EndNode | DecisionNode | WorkflowNodeRef;
export type WorkflowEdge = { from: string; to: string };
export type LoopPolicy = { target_node_id: string; max_iterations: number };
export type WorkflowDefinition = { schema_version: "v1"; name: string; nodes: WorkflowNode[]; edges: WorkflowEdge[]; phases?: unknown[] };
export type Position = { x: number; y: number };
export type Viewport = { x: number; y: number; zoom: number };
export type WorkflowEditorState = { definition: WorkflowDefinition; layout: { positions: Record<string, Position>; viewport: Viewport }; selection: { nodeIds: string[]; edge?: WorkflowEdge } };

/**
 * Result of the JSON paste controls' safe-parse contract: text enters editor
 * state only when it parses AND matches the authoring shape. `malformed` marks
 * syntactically broken JSON; `kind` marks parseable JSON of the wrong container
 * (an object where a FormField array belongs, a list where an object belongs);
 * `shape` marks the right container whose entries do not satisfy the target
 * authoring type (e.g. `[{}]` against FormField[]).
 */
export type JsonParseResult<T> = { ok: true; value: T } | { ok: false; reason: "malformed" | "kind" | "shape" };

const FORM_FIELD_TYPES = ["string", "number", "boolean"] as const;

function isPlainObject(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

/** Structural FormField contract (backend FormField types only; pattern/semantic issues stay reportable). */
function isFormField(value: unknown): value is FormField {
  return isPlainObject(value) && typeof value.name === "string" && typeof value.required === "boolean" && (FORM_FIELD_TYPES as readonly unknown[]).includes(value.type);
}

function parseJsonText<T>(text: string, kind: (value: unknown) => boolean, check: (value: unknown) => value is T): JsonParseResult<T> {
  let parsed: unknown;
  try { parsed = JSON.parse(text); } catch { return { ok: false, reason: "malformed" }; }
  if (!kind(parsed)) return { ok: false, reason: "kind" };
  return check(parsed) ? { ok: true, value: parsed } : { ok: false, reason: "shape" };
}

/** Safe-parse for the Start `input_form` paste control: a JSON array of FormField-shaped objects. */
export function parseFormFieldArray(text: string): JsonParseResult<FormField[]> {
  return parseJsonText(text, Array.isArray, (value): value is FormField[] => (value as unknown[]).every(isFormField));
}

/** Safe-parse for object-valued paste controls (validation params_schema); unknown keys are preserved. */
export function parseJsonObject(text: string): JsonParseResult<Record<string, unknown>> {
  return parseJsonText(text, isPlainObject, (value): value is Record<string, unknown> => isPlainObject(value));
}

export { createNode, deserializeWorkflow, serializeWorkflow, validateWorkflow };

export function selectNode(state: WorkflowEditorState, nodeId?: string): WorkflowEditorState {
  return { ...state, selection: { nodeIds: nodeId && state.definition.nodes.some((node) => node.id === nodeId) ? [nodeId] : [] } };
}

export function updateNode(state: WorkflowEditorState, nodeId: string, update: Partial<WorkflowNode>): WorkflowEditorState {
  return deriveInputs({ ...state, definition: { ...state.definition, nodes: state.definition.nodes.map((node) => node.id === nodeId ? { ...node, ...update, id: node.id } as WorkflowNode : node) } });
}

export function deriveInputs(state: WorkflowEditorState): WorkflowEditorState {
  const byId = new Map(state.definition.nodes.map((node) => [node.id, node]));
  const nodes = state.definition.nodes.map((node) => {
    if (node.type === "start" || node.type === "decision") return node;
    const values: string[] = [];
    for (const edge of state.definition.edges) if (edge.to === node.id) {
      const source = byId.get(edge.from);
      const outputs = source?.type === "start" ? source.input_form.map((field) => field.name) : source && "outputs" in source ? source.outputs : [];
      for (const value of outputs) if (!values.includes(value)) values.push(value);
    }
    return { ...node, inputs: values } as WorkflowNode;
  });
  return { ...state, definition: { ...state.definition, nodes } };
}

export function deleteNode(state: WorkflowEditorState, nodeId: string): WorkflowEditorState {
  if (state.definition.nodes.find((node) => node.id === nodeId)?.type === "start" || state.definition.nodes.find((node) => node.id === nodeId)?.type === "end") return state;
  const positions = { ...state.layout.positions }; delete positions[nodeId];
  return deriveInputs({ ...state, definition: { ...state.definition, nodes: state.definition.nodes.filter((node) => node.id !== nodeId), edges: state.definition.edges.filter((edge) => edge.from !== nodeId && edge.to !== nodeId) }, layout: { ...state.layout, positions }, selection: { nodeIds: state.selection.nodeIds.filter((id) => id !== nodeId) } });
}

export function deleteEdge(state: WorkflowEditorState, edge: WorkflowEdge): WorkflowEditorState {
  return deriveInputs({ ...state, definition: { ...state.definition, edges: state.definition.edges.filter((item) => item.from !== edge.from || item.to !== edge.to) }, selection: { nodeIds: state.selection.nodeIds } });
}

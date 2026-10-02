import type { components } from "@/api/schema";
import { createNode } from "./nodeDefaults";
import { deserializeWorkflow, serializeWorkflow } from "./serialization";
import { validateWorkflow } from "./validation";

type Api = components["schemas"];
export type WorkflowNode = Api["StartNode"] | Api["ScriptNode"] | Api["HttpNode"] | Api["AiNode"] | Api["EndNode"] | { type: "decision"; id: string; selected_next_node_id: string } | { type: "workflow"; id: string; workflow_id: string };
export type WorkflowEdge = { from: string; to: string };
export type WorkflowPhase = Api["Phase"];
export type WorkflowDefinition = Omit<Api["WorkflowDefinition"], "nodes" | "edges"> & { nodes: WorkflowNode[]; edges: WorkflowEdge[]; phases?: WorkflowPhase[] | null };
export type Position = { x: number; y: number };
export type Viewport = { x: number; y: number; zoom: number };
export type WorkflowEditorState = { definition: WorkflowDefinition; layout: { positions: Record<string, Position>; viewport: Viewport }; selection: { nodeIds: string[]; edge?: WorkflowEdge } };
export { createNode, deserializeWorkflow, serializeWorkflow, validateWorkflow };

export function selectNode(state: WorkflowEditorState, nodeId?: string): WorkflowEditorState {
  return { ...state, selection: { nodeIds: nodeId && state.definition.nodes.some((node) => node.id === nodeId) ? [nodeId] : [] } };
}

export function updateNode(state: WorkflowEditorState, nodeId: string, update: Partial<WorkflowNode>): WorkflowEditorState {
  return { ...state, definition: { ...state.definition, nodes: state.definition.nodes.map((node) => node.id === nodeId ? { ...node, ...update, id: node.id } as WorkflowNode : node) } };
}

export function deleteNode(state: WorkflowEditorState, nodeId: string): WorkflowEditorState {
  const positions = { ...state.layout.positions }; delete positions[nodeId];
  return { ...state, definition: { ...state.definition, nodes: state.definition.nodes.filter((node) => node.id !== nodeId), edges: state.definition.edges.filter((edge) => edge.from !== nodeId && edge.to !== nodeId), phases: state.definition.phases?.map((phase) => ({ ...phase, node_ids: phase.node_ids.filter((id) => id !== nodeId) })) }, layout: { ...state.layout, positions }, selection: { nodeIds: state.selection.nodeIds.filter((id) => id !== nodeId) } };
}

export function deleteEdge(state: WorkflowEditorState, edge: WorkflowEdge): WorkflowEditorState {
  return { ...state, definition: { ...state.definition, edges: state.definition.edges.filter((item) => item.from !== edge.from || item.to !== edge.to) }, selection: { nodeIds: state.selection.nodeIds } };
}

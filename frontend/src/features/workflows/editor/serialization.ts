import type { WorkflowDefinition, WorkflowEditorState } from "./model";

export function serializeWorkflow(state: WorkflowEditorState): WorkflowDefinition {
  const ids = new Set<string>();
  for (const node of state.definition.nodes) {
    if (ids.has(node.id)) throw new Error(`Duplicate node ID: ${node.id}`);
    ids.add(node.id);
  }
  return structuredClone(state.definition);
}

export function deserializeWorkflow(definition: WorkflowDefinition, layout?: WorkflowEditorState["layout"]): WorkflowEditorState {
  const positions = layout?.positions ?? Object.fromEntries(definition.nodes.map((node, index) => [node.id, { x: index * 220, y: 0 }]));
  return { definition: structuredClone(definition), layout: { positions: structuredClone(positions), viewport: layout?.viewport ?? { x: 0, y: 0, zoom: 1 } }, selection: { nodeIds: [] } };
}

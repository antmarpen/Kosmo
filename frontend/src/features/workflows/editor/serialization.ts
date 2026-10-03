import type { WorkflowDefinition, WorkflowEditorState } from "./model";
import { deriveInputs } from "./model";

export function serializeWorkflow(state: WorkflowEditorState): WorkflowDefinition {
  const ids = new Set<string>();
  for (const node of state.definition.nodes) {
    if (ids.has(node.id)) throw new Error(`Duplicate node ID: ${node.id}`);
    ids.add(node.id);
  }
  return structuredClone(state.definition);
}

export function deserializeWorkflow(definition: WorkflowDefinition, layout?: WorkflowEditorState["layout"]): WorkflowEditorState {
  const sourceNodes = structuredClone(definition.nodes).map((node) => node.type === "start"
    ? { ...node, input_form: node.input_form.map(({ name, type, required }) => ({ name, type, required })) }
    : node);
  const retained = new Map<string, string>();
  const structural = new Map<string, string>();
  const unique = sourceNodes.filter((node) => {
    if (node.type !== "start" && node.type !== "end") return true;
    const first = structural.get(node.type);
    if (!first) { structural.set(node.type, node.id); retained.set(node.id, node.id); return true; }
    retained.set(node.id, first); return false;
  });
  const fixed = (type: "start" | "end", position: { x: number; y: number }) => {
    const existing = unique.find((node) => node.type === type);
    if (existing) return existing;
    let id: string = type, suffix = 1;
    while (unique.some((node) => node.id === id)) id = `${type}-${suffix++}`;
    const node = type === "start" ? { type, id, input_form: [] } : { type, id, inputs: [] };
    unique.push(node);
    generatedPositions[id] = position;
    return node;
  };
  const generatedPositions: Record<string, { x: number; y: number }> = {};
  fixed("start", { x: 0, y: 0 }); fixed("end", { x: Math.max(220, unique.length * 220), y: 0 });
  const nodes = unique;
  const positions = { ...Object.fromEntries(nodes.map((node, index) => [node.id, { x: index * 220, y: 0 }])), ...layout?.positions, ...generatedPositions };
  const present = new Set(nodes.map((node) => node.id));
  const edges = new Map<string, { from: string; to: string }>();
  for (const edge of definition.edges) { const from = retained.get(edge.from) ?? edge.from, to = retained.get(edge.to) ?? edge.to; if (present.has(from) && present.has(to)) edges.set(`${from}->${to}`, { from, to }); }
  const cleanDefinition = { ...structuredClone(definition), nodes, edges: [...edges.values()] };
  return deriveInputs({ definition: cleanDefinition, layout: { positions: Object.fromEntries(Object.entries(positions).filter(([id]) => present.has(id))), viewport: layout?.viewport ?? { x: 0, y: 0, zoom: 1 } }, selection: { nodeIds: [] } });
}

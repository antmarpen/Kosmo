import type { WorkflowEditorState, WorkflowNode } from "./model";

export type ValidationResult = { level: "valid" | "warning" | "error"; nodeErrors: Record<string, string[]>; globalErrors: string[] };
export function validateWorkflow(state: WorkflowEditorState): ValidationResult {
  const { nodes, edges } = state.definition;
  const nodeErrors: Record<string, string[]> = {};
  const globalErrors: string[] = [];
  const add = (id: string, message: string) => { (nodeErrors[id] ??= []).push(message); };
  const starts = nodes.filter((node) => node.type === "start");
  if (!starts.length) globalErrors.push("Workflow requires a start node.");
  const ends = nodes.filter((node) => node.type === "end");
  if (!ends.length) globalErrors.push("Workflow requires an end node.");
  const ids = new Set<string>();
  for (const node of nodes) {
    if (ids.has(node.id)) add(node.id, "Duplicate node ID.");
    ids.add(node.id);
    validateNode(node, add);
  }
  if (starts.length) {
    const adjacency = new Map(nodes.map((node) => [node.id, [] as string[]]));
    for (const edge of edges) adjacency.get(edge.from)?.push(edge.to);
    const reached = new Set<string>(), pending = [starts[0].id];
    while (pending.length) { const id = pending.pop()!; if (reached.has(id)) continue; reached.add(id); pending.push(...(adjacency.get(id) ?? [])); }
    for (const node of nodes) if (!reached.has(node.id)) add(node.id, "Node is not reachable from the start node.");
    if (ends.length && !ends.some((node) => reached.has(node.id))) globalErrors.push("No end node is reachable from the start node.");
  }
  const hasNodeErrors = Object.keys(nodeErrors).length > 0;
  return { level: globalErrors.length || hasNodeErrors ? "error" : "valid", nodeErrors, globalErrors };
}

function validateNode(node: WorkflowNode, add: (id: string, error: string) => void) {
  switch (node.type) {
    case "script": if (!node.code.trim()) add(node.id, "Code is required."); break;
    case "http": if (!node.method.trim()) add(node.id, "Method is required."); if (!node.url.trim()) add(node.id, "URL is required."); break;
    case "ai": if (!node.agent.model.trim()) add(node.id, "Model is required."); if (!node.prompt_template.trim()) add(node.id, "Prompt template is required."); if (node.validation.levels.length !== 3) add(node.id, "Exactly three validation levels are required."); break;
    case "workflow": if (!node.workflow_id.trim()) add(node.id, "Workflow reference is required."); break;
    case "decision": if (!node.selected_next_node_id.trim()) add(node.id, "Decision route is required."); break;
  }
}

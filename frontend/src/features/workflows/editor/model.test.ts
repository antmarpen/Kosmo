import { describe, expect, it } from "vitest";
import { createNode, deleteEdge, deleteNode, deserializeWorkflow, serializeWorkflow, validateWorkflow, type WorkflowEditorState, type WorkflowNode } from "./model";

const nodes: WorkflowNode[] = [
  { type: "start", id: "start", input_form: [] },
  { type: "script", id: "script", code: "", inputs: [], outputs: [] },
  { type: "http", id: "http", method: "GET", url: "", outputs: [] },
  { type: "ai", id: "ai", agent: { runtime: "opencode", model: "", instructions: "" }, prompt_template: "", inputs: [], outputs: [], validation: { levels: [{ name: "one", message_key: "one", params_schema: {} }, { name: "two", message_key: "two", params_schema: {} }, { name: "three", message_key: "three", params_schema: {} }] }, max_validation_cycles: 3 },
  { type: "decision", id: "decision", selected_next_node_id: "" },
  { type: "workflow", id: "workflow", workflow_id: "" },
  { type: "end", id: "end" },
];

function state(definitionNodes: WorkflowEditorState["definition"]["nodes"] = [nodes[0], nodes[6]], edges: WorkflowEditorState["definition"]["edges"] = [{ from: "start", to: "end" }]): WorkflowEditorState {
  return { definition: { schema_version: "v1", name: "Test", nodes: [...definitionNodes], edges, phases: [{ id: "phase", node_ids: ["start", "end"], loop: { target_node_id: "start", max_iterations: 2 } }] }, layout: { positions: { start: { x: 1, y: 2 }, end: { x: 3, y: 4 } }, viewport: { x: 0, y: 0, zoom: 1 } }, selection: { nodeIds: ["start"] } };
}

describe("workflow editor model", () => {
  it("round-trips all seven schema node variants and schema-only phase data", () => {
    const original = state([...nodes]);
    expect(serializeWorkflow(deserializeWorkflow(original.definition, original.layout))).toEqual(original.definition);
    expect(serializeWorkflow(deserializeWorkflow(original.definition, original.layout)).phases).toEqual(original.definition.phases);
  });
  it("keeps canvas layout and selection separate from serialized definitions", () => {
    const original = state();
    const editor = deserializeWorkflow(original.definition, original.layout);
    expect(serializeWorkflow(editor)).not.toHaveProperty("layout");
    expect(editor.layout.positions.start).toEqual({ x: 1, y: 2 });
  });
  it("deletes a node and its incident edges, or a selected edge", () => {
    const initial = state([nodes[0], nodes[1], nodes[6]], [{ from: "start", to: "script" }, { from: "script", to: "end" }]);
    expect(deleteNode(initial, "script").definition.edges).toEqual([]);
    expect(deleteEdge(initial, { from: "start", to: "script" }).definition.edges).toEqual([{ from: "script", to: "end" }]);
  });
  it("rejects duplicate node IDs", () => {
    expect(() => serializeWorkflow(state([nodes[0], { ...nodes[6], id: "start" }]))).toThrow(/duplicate/i);
  });
  it("allows incomplete node fields in a saved draft", () => {
    expect(() => serializeWorkflow(state([nodes[0], nodes[1], nodes[6]], [{ from: "start", to: "script" }, { from: "script", to: "end" }]))).not.toThrow();
  });
  it("returns field-level node errors and global graph summary errors", () => {
    const result = validateWorkflow(state([nodes[0], nodes[1]], []));
    expect(result.level).toBe("error");
    expect(result.nodeErrors.script).toBeDefined();
    expect(result.globalErrors.length).toBeGreaterThan(0);
  });
  it("provides defaults for Decision and Workflow nodes", () => {
    expect(createNode("decision", "d")).toEqual({ type: "decision", id: "d", selected_next_node_id: "" });
    expect(createNode("workflow", "w")).toEqual({ type: "workflow", id: "w", workflow_id: "" });
  });
});

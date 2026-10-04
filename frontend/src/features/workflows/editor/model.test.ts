import { describe, expect, it } from "vitest";
import { createNode, deleteEdge, deleteNode, deserializeWorkflow, parseFormFieldArray, parseJsonObject, serializeWorkflow, validateWorkflow, type WorkflowEditorState, type WorkflowNode } from "./model";

const nodes: WorkflowNode[] = [
  { type: "start", id: "start", input_form: [] },
  { type: "script", id: "script", code: "", inputs: [], outputs: [] },
  { type: "http", id: "http", method: "GET", url: "", inputs: [], outputs: ["response"] },
  { type: "ai", id: "ai", agent_id: "agent-uuid", prompt_template: "", inputs: [], outputs: ["artifact"], output_validation: { artifact: { format: "json", json_schema: { type: "object" }, rules_code: "return True" } }, max_validation_cycles: 3 },
  { type: "decision", id: "decision", selected_next_node_id: "" },
  { type: "workflow", id: "workflow", workflow_id: "", inputs: [] },
  { type: "end", id: "end", inputs: [] },
];

function state(definitionNodes: WorkflowEditorState["definition"]["nodes"] = [nodes[0], nodes[6]], edges: WorkflowEditorState["definition"]["edges"] = [{ from: "start", to: "end" }]): WorkflowEditorState {
  return { definition: { schema_version: "v1", name: "Test", nodes: [...definitionNodes], edges }, layout: { positions: { start: { x: 1, y: 2 }, end: { x: 3, y: 4 } }, viewport: { x: 0, y: 0, zoom: 1 } }, selection: { nodeIds: ["start"] } };
}

describe("workflow editor model", () => {
  it("repairs fixed structural nodes and derives contracts from connected producers", () => {
    const loaded = deserializeWorkflow({ schema_version: "v1", name: "x", nodes: [{ type: "script", id: "s", code: "", inputs: [], outputs: ["result"] }], edges: [] });
    expect(loaded.definition.nodes.filter((node) => node.type === "start")).toHaveLength(1);
    expect(loaded.definition.nodes.filter((node) => node.type === "end")).toHaveLength(1);
    expect(deleteNode(loaded, loaded.definition.nodes.find((node) => node.type === "start")!.id).definition.nodes.some((node) => node.type === "start")).toBe(true);
  });
  it("round-trips all seven schema node variants", () => {
    const original = state([...nodes]);
    expect(serializeWorkflow(deserializeWorkflow(original.definition, original.layout))).toEqual(original.definition);
  });
  it("serializes AI nodes as reference-only canonical JSON while preserving phase and output contracts", () => {
    const ai = { type: "ai" as const, id: "ai", agent_id: "agent", model: "chosen", added_mcp_ids: [], prompt_template: "p", inputs: [], outputs: ["out"], output_validation: { out: { format: "markdown" as const } }, max_validation_cycles: 3 };
    const original = state([nodes[0], ai, nodes[6]]);
    original.definition.phases = [{ id: "phase" }];
    expect(serializeWorkflow(original).nodes[1]).toEqual({ type: "ai", id: "ai", agent_id: "agent", model: "chosen", prompt_template: "p", inputs: [], outputs: ["out"], output_validation: { out: { format: "markdown" } }, max_validation_cycles: 3 });
    expect(serializeWorkflow(original).phases).toEqual([{ id: "phase" }]);
  });
  it("normalizes graph-derived inputs on load, preserves phases, and preserves ordered producer outputs", () => {
    const definition = { ...state([nodes[0], { ...(nodes[1] as Extract<WorkflowNode, { type: "script" }>), inputs: ["stale"], outputs: ["a", "b"] }, { ...(nodes[2] as Extract<WorkflowNode, { type: "http" }>), inputs: ["stale"] }, nodes[6]], [{ from: "start", to: "script" }, { from: "script", to: "end" }, { from: "start", to: "end" }]).definition, phases: [{ id: "phase-1" }] };
    const loaded = deserializeWorkflow(definition);
    expect((loaded.definition.nodes.find((n) => n.id === "script") as Extract<WorkflowNode, { type: "script" }>).inputs).toEqual([]);
    expect((loaded.definition.nodes.find((n) => n.id === "end") as Extract<WorkflowNode, { type: "end" }>).inputs).toEqual(["a", "b"]);
    expect(serializeWorkflow(loaded)).toMatchObject({ phases: definition.phases });
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
    const disconnected = deleteEdge(initial, { from: "start", to: "script" });
    expect(disconnected.definition.edges).toEqual([{ from: "script", to: "end" }]);
    expect(disconnected.definition.nodes.find((node) => node.id === "script")).toMatchObject({ inputs: [] });
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
    expect(createNode("workflow", "w")).toEqual({ type: "workflow", id: "w", workflow_id: "", inputs: [] });
  });
});

describe("safe JSON paste parsing", () => {
  const validField = { name: "topic", type: "string", required: true };

  it("accepts a structurally valid FormField array, including the empty array", () => {
    expect(parseFormFieldArray(JSON.stringify([validField]))).toEqual({ ok: true, value: [validField] });
    expect(parseFormFieldArray("[]")).toEqual({ ok: true, value: [] });
  });

  it("rejects a non-array value as a container-kind failure", () => {
    expect(parseFormFieldArray('{"name":"topic"}')).toEqual({ ok: false, reason: "kind" });
  });

  it.each([
    ["[{}]"],
    ['[{"name":3,"type":"string","required":true}]'],
    ['[{"name":"topic","type":"string"}]'],
    ['[{"name":"topic","type":"integer","required":true}]'],
    ['[{"name":"topic","type":"string","required":"yes"}]'],
    ['["topic"]'],
    ["[null]"],
    ["[[]]"],
  ])("rejects structurally invalid form entries as shape failures: %j", (text) => {
    expect(parseFormFieldArray(text)).toEqual({ ok: false, reason: "shape" });
  });

  it("rejects malformed JSON as a syntax failure", () => {
    expect(parseFormFieldArray("[{")).toEqual({ ok: false, reason: "malformed" });
    expect(parseFormFieldArray("not json")).toEqual({ ok: false, reason: "malformed" });
  });

  it("accepts JSON objects for validation schema and preserves unknown keys verbatim", () => {
    const text = '{"artifact":"summary.md","custom_flag":true,"unknown_key":[1,2]}';
    expect(parseJsonObject(text)).toEqual({ ok: true, value: { artifact: "summary.md", custom_flag: true, unknown_key: [1, 2] } });
  });

  it.each(["[]", '"text"', "3", "null"])("rejects non-object params as container-kind failures: %j", (text) => {
    expect(parseJsonObject(text)).toEqual({ ok: false, reason: "kind" });
  });

  it("rejects malformed params JSON as a syntax failure", () => {
    expect(parseJsonObject('{"artifact":')).toEqual({ ok: false, reason: "malformed" });
  });

  it("round-trips a valid pasted input_form and edited schema through save/reload", () => {
    const form = parseFormFieldArray(JSON.stringify([validField]));
    const params = parseJsonObject('{"artifact":"summary.md","custom_flag":true}');
    expect(form.ok && params.ok).toBe(true);
    if (!form.ok || !params.ok) return;
    const aiNode = createNode("ai", "ai");
    if (aiNode.type === "ai") { aiNode.outputs = ["artifact"]; aiNode.output_validation = { artifact: { format: "json", json_schema: { type: "object" }, rules_code: "return True" } }; }
    const editor = deserializeWorkflow({ schema_version: "v1", name: "test", nodes: [createNode("start", "start"), aiNode, createNode("end", "end")], edges: [{ from: "start", to: "ai" }, { from: "ai", to: "end" }] });
    editor.selection.nodeIds = ["start"];
    const saved = serializeWorkflow({
      ...editor,
      definition: { ...editor.definition, nodes: editor.definition.nodes.map((node) => (node.type === "start" ? { ...node, input_form: form.value } : node.type === "ai" ? { ...node, output_validation: { artifact: { format: "json", json_schema: params.value } } } : node)) },
    });
    const reloaded = deserializeWorkflow(saved);
    const start = reloaded.definition.nodes.find((node) => node.id === "start") as Extract<WorkflowNode, { type: "start" }>;
    const ai = reloaded.definition.nodes.find((node) => node.id === "ai") as Extract<WorkflowNode, { type: "ai" }>;
    expect(start.input_form).toEqual([validField]);
    expect(ai.output_validation?.artifact).toEqual({ format: "json", json_schema: { artifact: "summary.md", custom_flag: true } });
    expect(validateWorkflow(reloaded).nodeErrors["start"]).toBeUndefined();
  });
});

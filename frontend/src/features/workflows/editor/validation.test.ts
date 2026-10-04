import { describe, expect, it } from "vitest";
import { createNode, deserializeWorkflow, serializeWorkflow, type WorkflowEditorState, type WorkflowNode } from "./model";
import { locateServerIssues, validateWorkflow } from "./validation";

/** Editor state over a start → script → end graph (script fails validation: empty code). */
function stateWith(nodes: Parameters<typeof createNode>[0][], edges: { from: string; to: string }[] = []): WorkflowEditorState {
  return deserializeWorkflow({ schema_version: "v1", name: "test", nodes: nodes.map((type, index) => createNode(type, `${type}-${index}`)), edges });
}

/** Mutates a node with raw (possibly schema-breaking) values, as an opaque server-loaded draft could. */
function withRaw(node: WorkflowNode, patch: Record<string, unknown>): WorkflowNode {
  return { ...node, ...patch } as WorkflowNode;
}

describe("client-side workflow validation", () => {
  it("reports duplicate artifact names from direct producers on the receiving node", () => {
    const state = deserializeWorkflow({ schema_version: "v1", name: "test", nodes: [
      { type: "start", id: "s", input_form: [] },
      { type: "script", id: "a", code: "x", inputs: [], outputs: ["shared"] },
      { type: "script", id: "b", code: "x", inputs: [], outputs: ["shared"] },
      { type: "end", id: "e", inputs: [] },
    ], edges: [{ from: "s", to: "e" }, { from: "a", to: "e" }, { from: "b", to: "e" }] });
    expect(validateWorkflow(state).nodeErrors.e).toContainEqual({ message_key: "workflowEditor.validation.duplicateProducer" });
    expect((state.definition.nodes.find((node) => node.id === "e") as Extract<WorkflowNode, { type: "end" }>).inputs).toEqual(["shared"]);
  });
  it("returns catalog-keyed issues located per node, not English strings", () => {
    const state = stateWith(["start", "script", "end"], [{ from: "start-0", to: "script-1" }, { from: "script-1", to: "end-2" }]);
    const result = validateWorkflow(state);

    expect(result.level).toBe("error");
    expect(result.nodeErrors["script-1"]).toEqual([{ message_key: "workflowEditor.validation.codeRequired" }]);
    expect(result.globalErrors).toEqual([]);
  });

  it("locates graph-level gaps on the summary and per-node problems on the nodes", () => {
    const state = stateWith(["start", "script", "end"]);
    const result = validateWorkflow(state);

    expect(result.globalErrors).toEqual([{ message_key: "workflowEditor.validation.noReachableEnd" }]);
    expect(Object.keys(result.nodeErrors).sort()).toEqual(["end-2", "script-1"]);
    expect(result.nodeErrors["end-2"]).toEqual([{ message_key: "workflowEditor.validation.unreachable" }]);
  });

  it("reports field-specific issues with their params", () => {
    const state = stateWith(["start", "http", "end"], [{ from: "start-0", to: "http-1" }, { from: "http-1", to: "end-2" }]);
    const http = state.definition.nodes[1];
    const result = validateWorkflow(state);

    expect(result.nodeErrors[http.id]).toEqual([{ message_key: "workflowEditor.validation.urlRequired" }]);
    expect(result.level).toBe("error");
  });

  it("reports localized issues for a semantically invalid but structurally valid form, and the draft stays saveable", () => {
    const state = stateWith(["start"]);
    (state.definition.nodes[0] as WorkflowNode & { input_form: unknown }).input_form = [
      { name: "my field", type: "string", required: true },
    ];
    const result = validateWorkflow(state);

    expect(() => validateWorkflow(state)).not.toThrow();
    expect(result.level).toBe("error");
    expect(result.nodeErrors["start-0"]).toEqual(expect.arrayContaining([
      { message_key: "workflowEditor.validation.startFieldNameInvalid", params: { index: 1 } },
    ]));
    expect(() => serializeWorkflow(state)).not.toThrow();
  });
});

describe("client-side validation never throws on structurally broken state", () => {
  // These shapes must never reach editor state through the JSON controls, but
  // an opaque server-loaded draft could still carry them, so validation degrades
  // to localized issues instead of crashing the editor.
  it("survives a start form with missing keys and reports the localized gaps", () => {
    const state = stateWith(["start"]);
    state.definition.nodes[0] = withRaw(state.definition.nodes[0], { input_form: [{}] });
    let result!: ReturnType<typeof validateWorkflow>;
    expect(() => { result = validateWorkflow(state); }).not.toThrow();
    expect(result.nodeErrors["start-0"]).toEqual(expect.arrayContaining([
      { message_key: "workflowEditor.validation.startFieldNameRequired", params: { index: 1 } },
    ]));
  });

  it("survives mistyped field values (name: 3) and reports localized issues", () => {
    const state = stateWith(["start"]);
    state.definition.nodes[0] = withRaw(state.definition.nodes[0], { input_form: [{ name: 3, type: "string", required: true }] });
    let result!: ReturnType<typeof validateWorkflow>;
    expect(() => { result = validateWorkflow(state); }).not.toThrow();
    expect(Object.keys(result.nodeErrors)).toContain("start-0");
    expect(result.nodeErrors["start-0"].every((issue) => issue.message_key.startsWith("workflowEditor.validation."))).toBe(true);
  });

  it("survives a non-array input_form and obsolete AI node-wide validation", () => {
    const broken = stateWith(["start", "ai"]);
    broken.definition.nodes[0] = withRaw(broken.definition.nodes[0], { input_form: {} });
    broken.definition.nodes[1] = withRaw(broken.definition.nodes[1], { validation: {} });
    let result!: ReturnType<typeof validateWorkflow>;
    expect(() => { result = validateWorkflow(broken); }).not.toThrow();
    expect(result.nodeErrors["ai-1"]).toEqual(expect.arrayContaining([
      expect.objectContaining({ message_key: "workflowEditor.validation.agentRequired" }),
    ]));
  });
});

describe("server draft-validation issue mapping", () => {
  it("maps issues carrying a node_id to that node", () => {
    const state = stateWith(["start", "script", "end"]);
    const { nodeErrors, globalErrors } = locateServerIssues(
      [{ message_key: "errors.workflow.workflow_not_found", params: { node_id: "script-1", workflow_id: "absent" } }],
      state.definition.nodes,
    );

    expect(nodeErrors["script-1"]).toEqual([
      { message_key: "errors.workflow.workflow_not_found", params: { node_id: "script-1", workflow_id: "absent" } },
    ]);
    expect(globalErrors).toEqual([]);
  });

  it("maps issues carrying a definition field path to the node at that index", () => {
    const state = stateWith(["start", "script", "end"]);
    const { nodeErrors, globalErrors } = locateServerIssues(
      [{ message_key: "errors.workflow.invalid_definition", params: { field: "nodes.1.http.outputs.0", type: "string_pattern_mismatch" } }],
      state.definition.nodes,
    );

    expect(nodeErrors["script-1"]).toEqual([
      { message_key: "errors.workflow.invalid_definition", params: { field: "nodes.1.http.outputs.0", type: "string_pattern_mismatch" } },
    ]);
    expect(globalErrors).toEqual([]);
  });

  it("keeps issues that cannot be located as the summary", () => {
    const state = stateWith(["start", "end"]);
    const { nodeErrors, globalErrors } = locateServerIssues(
      [
        { message_key: "errors.workflow.cycle", params: {} },
        { message_key: "errors.workflow.invalid_definition", params: { field: "nodes.9.missing", type: "missing" } },
      ],
      state.definition.nodes,
    );

    expect(nodeErrors).toEqual({});
    expect(globalErrors).toEqual([
      { message_key: "errors.workflow.cycle", params: {} },
      { message_key: "errors.workflow.invalid_definition", params: { field: "nodes.9.missing", type: "missing" } },
    ]);
  });
});

import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useState } from "react";
import { describe, expect, it, vi } from "vitest";
import en from "@/i18n/locales/en.json";
import { createNode, deserializeWorkflow, updateNode, type WorkflowEditorState, type WorkflowNode } from "./model";
import { PropertiesPanel } from "./PropertiesPanel";

const { get } = vi.hoisted(() => ({ get: vi.fn() }));
vi.mock("@/api/auth", () => ({ api: { GET: get } }));

/**
 * Panel catalog keys are applied by the coordinator; until then i18next
 * renders the raw dotted key, so expectations resolve the value when present
 * and fall back to the full key path itself (same contract as
 * ScriptEditor.test.tsx).
 */
const editorCatalog = en.editor as unknown as Record<string, string | undefined>;
const expected = (key: string) => editorCatalog[key] ?? `editor.${key}`;

function stateWith(type: WorkflowNode["type"], id = "n"): WorkflowEditorState {
  const state = deserializeWorkflow({ schema_version: "v1", name: "test", nodes: [createNode(type, id)], edges: [] });
  state.selection.nodeIds = [id];
  return state;
}

/**
 * Applies updates through the real updateNode reducer like the editor page
 * does, so every assertion runs against the committed node state instead of
 * transient callback arguments.
 */
function renderPanel(initial: WorkflowEditorState) {
  const onUpdate = vi.fn();
  function Harness() {
    const [state, setState] = useState(initial);
    return <PropertiesPanel state={state} onUpdate={(id, patch) => { onUpdate(id, patch); setState((current) => updateNode(current, id, patch)); }} />;
  }
  render(<Harness />);
  return onUpdate;
}

const lastCommittedNode = (onUpdate: ReturnType<typeof vi.fn>) => onUpdate.mock.calls.at(-1)![1] as WorkflowNode;

describe("properties panel", () => {
  it("renders nothing without a selected node", () => {
    const state = deserializeWorkflow({ schema_version: "v1", name: "test", nodes: [createNode("start", "s")], edges: [] });
    render(<PropertiesPanel state={state} onUpdate={vi.fn()} />);
    // The panel exists only while a node is selected (spec: it appears on
    // selection and closes on canvas click); there is no empty placeholder.
    expect(screen.queryByRole("complementary")).not.toBeInTheDocument();
  });

  it("authors a schema-valid start input_form array through the field builder", async () => {
    const user = userEvent.setup();
    const onUpdate = renderPanel(stateWith("start"));
    await user.click(screen.getByRole("button", { name: expected("addField") }));
    await user.type(screen.getByLabelText(`${expected("fieldName")} 1`), "topic");
    await user.type(screen.getByLabelText(`${expected("fieldLabelKey")} 1`), "workflow.topic.label");
    // Defaults: the first schema type and a required field.
    expect(screen.getByLabelText(`${expected("fieldType")} 1`)).toHaveValue("string");
    expect(screen.getByLabelText(`${expected("fieldRequired")} 1`)).toBeChecked();
    const node = lastCommittedNode(onUpdate) as Extract<WorkflowNode, { type: "start" }>;
    // backend/shared/graph/schema.py FormField: name, type, required, label_message_key,
    // stored as an ARRAY (StartNode.input_form: list[FormField]).
    expect(node.input_form).toEqual([{ name: "topic", type: "string", required: true, label_message_key: "workflow.topic.label" }]);
  });

  it("removes start fields from the input_form array", async () => {
    const state = stateWith("start");
    (state.definition.nodes[0] as Extract<WorkflowNode, { type: "start" }>).input_form = [
      { name: "topic", type: "string", required: true, label_message_key: "workflow.topic.label" },
    ];
    const user = userEvent.setup();
    const onUpdate = renderPanel(state);
    await user.click(screen.getByRole("button", { name: `${expected("removeField")} 1` }));
    expect(lastCommittedNode(onUpdate)).toMatchObject({ type: "start", input_form: [] });
  });

  it("keeps a JSON paste path that accepts arrays for the start input_form", () => {
    const onUpdate = renderPanel(stateWith("start"));
    fireEvent.change(screen.getByLabelText(expected("inputFormJson")), {
      target: { value: '[{"name":"topic","type":"string","required":true,"label_message_key":"workflow.topic.label"}]' },
    });
    expect(lastCommittedNode(onUpdate)).toMatchObject({
      type: "start",
      input_form: [{ name: "topic", type: "string", required: true, label_message_key: "workflow.topic.label" }],
    });
  });

  it("rejects non-array JSON for the start input_form and keeps the committed value", () => {
    const state = stateWith("start");
    (state.definition.nodes[0] as Extract<WorkflowNode, { type: "start" }>).input_form = [
      { name: "topic", type: "string", required: true, label_message_key: "workflow.topic.label" },
    ];
    const onUpdate = renderPanel(state);
    fireEvent.change(screen.getByLabelText(expected("inputFormJson")), { target: { value: '{"name":"topic"}' } });
    expect(screen.getByRole("alert")).toHaveTextContent(expected("invalidJsonArray"));
    expect(onUpdate).not.toHaveBeenCalled();
  });

  it("does not commit malformed JSON and keeps the draft editable", () => {
    const onUpdate = renderPanel(stateWith("start"));
    const json = screen.getByLabelText(expected("inputFormJson"));
    fireEvent.change(json, { target: { value: "[{" } });
    expect(screen.getByRole("alert")).toHaveTextContent(expected("invalidJsonArray"));
    expect(onUpdate).not.toHaveBeenCalled();
    expect(json).toHaveValue("[{");
  });

  it("keeps structurally invalid entries ([{}], name: 3) out of editor state and reports them inline", () => {
    const state = stateWith("start");
    (state.definition.nodes[0] as Extract<WorkflowNode, { type: "start" }>).input_form = [
      { name: "topic", type: "string", required: true, label_message_key: "workflow.topic.label" },
    ];
    const onUpdate = renderPanel(state);
    const json = screen.getByLabelText(expected("inputFormJson"));
    for (const text of ["[{}]", '[{"name":3,"type":"string","required":true,"label_message_key":"workflow.topic.label"}]']) {
      fireEvent.change(json, { target: { value: text } });
      expect(screen.getByRole("alert")).toHaveTextContent(expected("invalidFormFieldArray"));
      // The last valid input_form stays committed; nothing that could crash
      // client validation enters editor state.
      expect(onUpdate).not.toHaveBeenCalled();
      expect(json).toHaveValue(text);
    }
  });

  it("commits again once the pasted array becomes structurally valid", () => {
    const onUpdate = renderPanel(stateWith("start"));
    const json = screen.getByLabelText(expected("inputFormJson"));
    fireEvent.change(json, { target: { value: "[{}]" } });
    expect(screen.getByRole("alert")).toHaveTextContent(expected("invalidFormFieldArray"));
    fireEvent.change(json, { target: { value: '[{"name":"topic","type":"number","required":false,"label_message_key":"workflow.topic.label"}]' } });
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
    expect(lastCommittedNode(onUpdate)).toMatchObject({
      input_form: [{ name: "topic", type: "number", required: false, label_message_key: "workflow.topic.label" }],
    });
  });

  it("edits each validation level params_schema as a JSON object and preserves unknown keys", () => {
    const onUpdate = renderPanel(stateWith("ai"));
    for (const index of [1, 2, 3]) expect(screen.getByLabelText(`${expected("levelParams")} ${index}`)).toBeInTheDocument();
    fireEvent.change(screen.getByLabelText(`${expected("levelParams")} 1`), { target: { value: '{"artifact":"summary.md","custom_flag":true}' } });
    const node = lastCommittedNode(onUpdate) as Extract<WorkflowNode, { type: "ai" }>;
    expect(node.validation.levels[0].params_schema).toEqual({ artifact: "summary.md", custom_flag: true });
    // The untouched levels keep their previous params.
    expect(node.validation.levels[1].params_schema).toEqual({});
    expect(node.validation.levels[2].params_schema).toEqual({});
  });

  it("keeps the last valid params when level params JSON is malformed or not an object", () => {
    const state = stateWith("ai");
    const ai = state.definition.nodes[0] as Extract<WorkflowNode, { type: "ai" }>;
    ai.validation.levels[0].params_schema = { artifact: "summary.md" };
    const onUpdate = renderPanel(state);
    const params = screen.getByLabelText(`${expected("levelParams")} 1`);
    fireEvent.change(params, { target: { value: '{"artifact":' } });
    expect(screen.getByRole("alert")).toHaveTextContent(expected("invalidJson"));
    fireEvent.change(params, { target: { value: '["artifact"]' } });
    expect(screen.getByRole("alert")).toHaveTextContent(expected("invalidJson"));
    expect(onUpdate).not.toHaveBeenCalled();
    expect(params).toHaveValue('["artifact"]');
  });

  it("round-trips declared script inputs and outputs", async () => {
    const user = userEvent.setup();
    const onUpdate = renderPanel(stateWith("script"));
    await user.click(screen.getByRole("button", { name: expected("addInput") }));
    await user.type(screen.getByLabelText(`${expected("inputs")} 1`), "topic");
    expect(lastCommittedNode(onUpdate)).toMatchObject({ type: "script", inputs: ["topic"] });
    await user.click(screen.getByRole("button", { name: expected("addOutput") }));
    await user.type(screen.getByLabelText(`${expected("outputs")} 1`), "report.md");
    expect(lastCommittedNode(onUpdate)).toMatchObject({ type: "script", inputs: ["topic"], outputs: ["report.md"] });
  });

  it("authors the ai agent config, declared io, and the three validation levels", async () => {
    const user = userEvent.setup();
    const onUpdate = renderPanel(stateWith("ai"));
    expect(screen.getByLabelText(expected("runtime"))).toHaveValue("opencode");
    await user.type(screen.getByLabelText(expected("model")), "claude-sonnet");
    await user.type(screen.getByLabelText(expected("instructions")), "Summarize the report.");
    await user.type(screen.getByLabelText(expected("prompt")), "Summarize the topic.");
    await user.click(screen.getByRole("button", { name: expected("addInput") }));
    await user.type(screen.getByLabelText(`${expected("inputs")} 1`), "report.md");
    await user.click(screen.getByRole("button", { name: expected("addOutput") }));
    await user.type(screen.getByLabelText(`${expected("outputs")} 1`), "summary.md");
    await user.clear(screen.getByLabelText(`${expected("levelName")} 2`));
    await user.type(screen.getByLabelText(`${expected("levelName")} 2`), "semantic");
    const node = lastCommittedNode(onUpdate) as Extract<WorkflowNode, { type: "ai" }>;
    expect(node.agent).toEqual({ runtime: "opencode", model: "claude-sonnet", instructions: "Summarize the report." });
    expect(node.prompt_template).toBe("Summarize the topic.");
    expect(node.inputs).toEqual(["report.md"]);
    expect(node.outputs).toEqual(["summary.md"]);
    // The validation contract keeps exactly three levels (schema min/max) with
    // editable name and message key; params_schema is preserved untouched.
    expect(node.validation.levels).toHaveLength(3);
    expect(node.validation.levels[1]).toEqual({ name: "semantic", message_key: "workflow.validation.semantic", params_schema: {} });
  });

  it("authors http method, url, and declared outputs without the rejected headers/body", async () => {
    const user = userEvent.setup();
    const onUpdate = renderPanel(stateWith("http"));
    expect(screen.queryByLabelText(expected("headers"))).not.toBeInTheDocument();
    expect(screen.queryByLabelText(expected("body"))).not.toBeInTheDocument();
    await user.selectOptions(screen.getByLabelText(expected("method")), "POST");
    await user.type(screen.getByLabelText(expected("url")), "https://example.test/api");
    await user.click(screen.getByRole("button", { name: expected("addOutput") }));
    await user.type(screen.getByLabelText(`${expected("outputs")} 1`), "status.json");
    const node = lastCommittedNode(onUpdate) as Extract<WorkflowNode, { type: "http" }>;
    expect(node).toEqual({ type: "http", id: "n", method: "POST", url: "https://example.test/api", outputs: ["status.json"] });
  });

  it("drops the schema-rejected legacy fields when an http node is edited", async () => {
    const state = stateWith("http");
    const http = state.definition.nodes[0] as Extract<WorkflowNode, { type: "http" }> & Record<string, unknown>;
    http.headers = { Authorization: "x" };
    http.body = "payload";
    const user = userEvent.setup();
    const onUpdate = renderPanel(state);
    await user.type(screen.getByLabelText(expected("url")), "https://example.test");
    const node = lastCommittedNode(onUpdate) as Record<string, unknown>;
    expect(node).not.toHaveProperty("headers");
    expect(node).not.toHaveProperty("body");
    expect(node.url).toBe("https://example.test");
  });

  it("offers no authoring controls for end nodes (schema v1 EndNode has none)", () => {
    renderPanel(stateWith("end"));
    expect(screen.queryByText(expected("outputMapping"))).not.toBeInTheDocument();
    expect(screen.queryByRole("textbox")).not.toBeInTheDocument();
    expect(screen.queryByRole("combobox")).not.toBeInTheDocument();
    expect(screen.queryByRole("checkbox")).not.toBeInTheDocument();
  });

  it("keeps the decision outgoing-target selection", async () => {
    const state = stateWith("decision");
    state.definition.nodes.push(createNode("end", "end"));
    state.definition.edges = [{ from: "n", to: "end" }];
    const user = userEvent.setup();
    const onUpdate = renderPanel(state);
    await user.selectOptions(screen.getByLabelText(expected("route")), "end");
    expect(lastCommittedNode(onUpdate)).toMatchObject({ type: "decision", selected_next_node_id: "end" });
  });

  it("lists workflows through the authenticated api client for the reference picker", async () => {
    get.mockResolvedValue({ data: [{ id: "wf-1", name: "Sample workflow", publication_revision: 1, active_version: null }] });
    const user = userEvent.setup();
    const onUpdate = renderPanel(stateWith("workflow"));
    const select = await screen.findByRole("combobox", { name: expected("workflow") });
    expect(get).toHaveBeenCalledWith("/workflows");
    await user.selectOptions(select, "wf-1");
    expect(lastCommittedNode(onUpdate)).toMatchObject({ type: "workflow", workflow_id: "wf-1" });
  });

  it("falls back to a text field when the workflow lookup fails", async () => {
    get.mockRejectedValue(new Error("offline"));
    const user = userEvent.setup();
    const onUpdate = renderPanel(stateWith("workflow"));
    await waitFor(() => expect(get).toHaveBeenCalled());
    const field = screen.getByLabelText(expected("workflow"));
    expect(field.tagName).toBe("INPUT");
    await user.type(field, "wf-remote");
    expect(lastCommittedNode(onUpdate)).toMatchObject({ type: "workflow", workflow_id: "wf-remote" });
  });
});

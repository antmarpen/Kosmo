import { render, screen, fireEvent } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { createNode, deserializeWorkflow, type WorkflowNode } from "./model";
import { PropertiesPanel } from "./PropertiesPanel";
import en from "@/i18n/locales/en.json";

vi.mock("@/api/auth", () => ({ api: { GET: vi.fn().mockResolvedValue({ data: [] }) } }));
vi.mock("./ScriptEditor", () => ({ ScriptEditor: () => <button>Edit script</button> }));
const expected = (key: string) => (en.editor as unknown as Record<string, string>)[key] ?? `editor.${key}`;
function renderType(type: WorkflowNode["type"], connected = false) {
  const nodes = [createNode(type, "n"), ...(connected ? [createNode("start", "s")] : [])];
  const state = deserializeWorkflow({ schema_version: "v1", name: "test", nodes, edges: connected ? [{ from: "s", to: "n" }] : [] });
  state.selection.nodeIds = ["n"];
  render(<PropertiesPanel state={state} onUpdate={vi.fn()} />);
}

describe("properties panel node contracts", () => {
  it("shows referenced workflow contracts, distinct from graph-derived chips", async () => {
    const workflow = createNode("workflow", "n") as Extract<WorkflowNode, { type: "workflow" }>;
    workflow.workflow_id = "child";
    const state = deserializeWorkflow({ schema_version: "v1", name: "test", nodes: [workflow], edges: [] });
    state.selection.nodeIds = ["n"];
    const { api } = await import("@/api/auth");
    vi.mocked(api.GET).mockResolvedValueOnce({ data: [{ id: "child", name: "Child", active_version: { definition: { nodes: [{ type: "start", input_form: [{ name: "long-input-name" }] }, { type: "end", inputs: ["output-name"] }] } } }], error: undefined } as never);
    render(<PropertiesPanel state={state} onUpdate={vi.fn()} />);
    expect(await screen.findByText("long-input-name")).toBeInTheDocument();
    expect(screen.getByText("output-name")).toBeInTheDocument();
  });
  it("uses a visual Start field builder and a required switch, without raw JSON or label key", () => {
    const start = createNode("start", "n") as Extract<WorkflowNode, { type: "start" }>;
    start.input_form = [{ name: "topic", type: "string", required: true }];
    const state = deserializeWorkflow({ schema_version: "v1", name: "test", nodes: [start], edges: [] });
    state.selection.nodeIds = ["n"];
    render(<PropertiesPanel state={state} onUpdate={vi.fn()} />);
    expect(screen.queryByText(/JSON array/i)).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: expected("addField") })).toBeInTheDocument();
    expect(screen.getByRole("switch", { name: `${expected("fieldRequired")} 1` })).toHaveAttribute("aria-checked", "true");
    expect(screen.queryByText(expected("fieldLabelKey"))).not.toBeInTheDocument();
    expect(screen.getAllByText(expected("inputs"))).toHaveLength(1);
    expect(screen.queryByText(expected("outputs"))).not.toBeInTheDocument();
  });
  it("shows graph inputs read-only, and script code only behind Edit script", () => {
    renderType("script", true);
    expect(screen.getByText(expected("inputs"))).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Edit script" })).toBeInTheDocument();
    expect(screen.queryByText(/print|return/)).not.toBeInTheDocument();
    expect(screen.getByText(expected("outputs"))).toBeInTheDocument();
  });
  it("shows fixed HTTP response output", () => {
    renderType("http");
    expect(screen.getByText("response")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: expected("addOutput") })).not.toBeInTheDocument();
  });
  it("opens a per-output validation modal for AI outputs", () => {
    const ai = createNode("ai", "n") as Extract<WorkflowNode, { type: "ai" }>;
    ai.outputs = ["answer"];
    const state = deserializeWorkflow({ schema_version: "v1", name: "test", nodes: [ai], edges: [] });
    state.selection.nodeIds = ["n"];
    render(<PropertiesPanel state={state} onUpdate={vi.fn()} />);
    fireEvent.click(screen.getByRole("button", { name: /validation.*answer/i }));
    expect(screen.getByRole("dialog")).toBeInTheDocument();
    expect(screen.getByText(expected("syntaxParse"))).toBeInTheDocument();
    expect(screen.getByText(expected("formatStructure"))).toBeInTheDocument();
    expect(screen.getByText(expected("rules"))).toBeInTheDocument();
  });
  it("exposes provenance for input chips", () => {
    const source = createNode("script", "source") as Extract<WorkflowNode, { type: "script" }>;
    source.outputs = ["artifact"];
    const target = createNode("script", "target") as Extract<WorkflowNode, { type: "script" }>;
    const state = deserializeWorkflow({ schema_version: "v1", name: "test", nodes: [source, target], edges: [{ from: "source", to: "target" }] });
    state.selection.nodeIds = ["target"];
    render(<PropertiesPanel state={state} onUpdate={vi.fn()} />);
    fireEvent.click(screen.getByRole("button", { name: /input information.*artifact/i }));
    expect(screen.getByText(expected("sourceNode"))).toBeInTheDocument();
    expect(screen.getByText(expected("outputKind"))).toBeInTheDocument();
    expect(screen.getByText(expected("validationSummary"))).toBeInTheDocument();
    expect(screen.getByRole("note").querySelector("dl")).toHaveClass("mt-3");
    expect(screen.getByRole("note").querySelector("dl")).toHaveClass("[&>dt]:font-medium");
  });
  it("lists contracts orphaned by output removal and preserves them until explicit removal", () => {
    const ai = createNode("ai", "n") as Extract<WorkflowNode, { type: "ai" }>;
    ai.outputs = [];
    ai.output_validation = { removed: { levels: [] } };
    const state = deserializeWorkflow({ schema_version: "v1", name: "test", nodes: [ai], edges: [] });
    state.selection.nodeIds = ["n"];
    const onUpdate = vi.fn();
    render(<PropertiesPanel state={state} onUpdate={onUpdate} />);
    expect(screen.getByText(expected("orphanedContract"))).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: /validation.*removed/i }));
    fireEvent.click(screen.getByRole("button", { name: expected("removeValidation") }));
    expect(onUpdate).toHaveBeenCalledWith("n", expect.objectContaining({ output_validation: {} }));
  });
  it("shows inputs but no outputs for End", () => {
    renderType("end", true);
    expect(screen.getByText(expected("inputs"))).toBeInTheDocument();
    expect(screen.queryByText(expected("outputs"))).not.toBeInTheDocument();
  });
  it("marks Decision as not functional", () => {
    renderType("decision");
    expect(screen.getByText(expected("decisionNotFunctional"))).toBeInTheDocument();
  });
});

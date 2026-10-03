import { render, screen } from "@testing-library/react";
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

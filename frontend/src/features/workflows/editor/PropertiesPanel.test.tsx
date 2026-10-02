import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { createNode, deserializeWorkflow } from "./model";
import { PropertiesPanel } from "./PropertiesPanel";

describe("properties panel", () => {
  it("shows empty state without a selected node", () => {
    const state = deserializeWorkflow({ schema_version: "v1", name: "test", nodes: [createNode("start", "s")], edges: [] });
    render(<PropertiesPanel state={state} onUpdate={vi.fn()} />);
    expect(screen.getByText("Select a node to edit its properties.")).toBeInTheDocument();
  });

  // Script is excluded: its properties are a read-only summary plus a modal
  // editor (covered in ScriptEditor.test.tsx), not a direct field.
  it.each(["start", "ai", "http", "decision", "workflow", "end"] as const)("renders and updates %s properties", (type) => {
    const state = deserializeWorkflow({ schema_version: "v1", name: "test", nodes: [createNode(type, "n")], edges: [] });
    state.selection.nodeIds = ["n"];
    if (type === "start") (state.definition.nodes[0] as any).input_form = {};
    if (type === "end") (state.definition.nodes[0] as any).output_mapping = {};
    const onUpdate = vi.fn();
    render(<PropertiesPanel state={state} onUpdate={onUpdate} />);
    expect(screen.getByRole("complementary", { name: /properties/i })).toBeInTheDocument();
    const field = screen.queryAllByRole("textbox")[0] ?? screen.getAllByRole("combobox")[0];
    fireEvent.change(field, { target: { value: field.tagName === "TEXTAREA" ? '{"updated":true}' : "updated" } });
    expect(onUpdate).toHaveBeenCalledWith("n", expect.objectContaining({ id: "n", type }));
  });
});

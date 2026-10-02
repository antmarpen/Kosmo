import { act, fireEvent, render, waitFor } from "@testing-library/react";
import { useState } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { Canvas, NODE_DRAG_MIME } from "./Canvas";
import { createNode, deserializeWorkflow, type WorkflowEditorState } from "./model";

// jsdom does not implement ResizeObserver, which React Flow requires for node
// measurement. Measurement is irrelevant to the selection coherence under test
// here, so a no-op stub is enough. Two jsdom limitations shape this file:
// without measurement React Flow renders no edges, and d3-drag pointer
// sequences cannot be simulated reliably; edge selection and drag behavior are
// therefore covered by the dedicated browser regression instead.
class ResizeObserverStub {
  observe() {}
  unobserve() {}
  disconnect() {}
}
vi.stubGlobal("ResizeObserver", ResizeObserverStub);

const baseDefinition = {
  schema_version: "v1" as const,
  name: "Test workflow",
  nodes: [createNode("start", "start"), createNode("end", "end")],
  edges: [{ from: "start", to: "end" }],
};

const baseState = (): WorkflowEditorState => ({
  ...deserializeWorkflow(baseDefinition),
  layout: { positions: { start: { x: 10, y: 20 }, end: { x: 200, y: 20 } }, viewport: { x: 0, y: 0, zoom: 1 } },
  selection: { nodeIds: [] },
});

type Captured = {
  selections: { nodeIds: string[]; edge?: { from: string; to: string } }[];
  deletions: number;
};

const emptyCaptured = (): Captured => ({ selections: [], deletions: 0 });

// Mirrors the exact controlled wiring EditorPage uses so the tests exercise
// the real feedback loop between editor state and React Flow's store.
function Host({ initial, captured }: { initial?: () => WorkflowEditorState; captured: Captured }) {
  const [state, setState] = useState<WorkflowEditorState>(initial ?? baseState);
  const select = (nodeIds: string[], edge?: { from: string; to: string }) => {
    captured.selections.push({ nodeIds, edge });
    setState((current) => {
      const sameNodes = current.selection.nodeIds.length === nodeIds.length && current.selection.nodeIds.every((id, index) => id === nodeIds[index]);
      const currentEdge = current.selection.edge;
      const sameEdge = (currentEdge === undefined && edge === undefined) || (currentEdge !== undefined && edge !== undefined && currentEdge.from === edge.from && currentEdge.to === edge.to);
      return sameNodes && sameEdge ? current : { ...current, selection: { nodeIds, edge } };
    });
  };
  return <div style={{ width: 800, height: 600 }}>
    <Canvas
      state={state}
      onPositionChange={(positions) => setState((current) => ({ ...current, layout: { ...current.layout, positions } }))}
      onSelectionChange={select}
      onConnect={(edge) => setState((current) => current.definition.edges.some((item) => item.from === edge.from && item.to === edge.to) ? current : ({ ...current, definition: { ...current.definition, edges: [...current.definition.edges, edge] } }))}
      onDeleteSelection={() => { captured.deletions += 1; }}
    />
    {/* Forces a fresh editor state object with identical values, recreating the
        nodes/edges arrays; selection must survive this update. */}
    <button type="button" onClick={() => setState((current) => ({ ...current }))}>bump</button>
  </div>;
}

const nodeElement = (id: string) => document.querySelector(`.react-flow__node[data-id="${id}"]`) as HTMLElement | null;

// Real users click the visible node body (the custom node component inside the
// positioned wrapper), so target the inner element for interaction.
const nodeBody = (id: string) => {
  const wrapper = nodeElement(id);
  return (wrapper?.firstElementChild as HTMLElement | null) ?? wrapper;
};

const bumpButton = () => [...document.querySelectorAll("button")].find((candidate) => candidate.textContent === "bump") as HTMLElement;

beforeEach(() => {
  document.body.innerHTML = "";
});

describe("workflow editor canvas (real React Flow)", () => {
  it("selects a node on single click and the selection persists across editor updates", async () => {
    const captured = emptyCaptured();
    render(<Host captured={captured} />);
    expect(nodeBody("start")).not.toBeNull();
    act(() => { fireEvent.click(nodeBody("start")!); });
    await waitFor(() => expect(nodeElement("start")).toHaveClass("selected"));
    expect(captured.selections.at(-1)?.nodeIds).toEqual(["start"]);
    // Recreate the editor state (fresh arrays, same values): selection survives.
    fireEvent.click(bumpButton());
    await waitFor(() => expect(nodeElement("start")).toHaveClass("selected"));
    expect(captured.selections.at(-1)?.nodeIds).toEqual(["start"]);
  });

  it("renders programmatic selection and does not loop selection notifications", async () => {
    const captured = emptyCaptured();
    const initial = () => ({ ...baseState(), selection: { nodeIds: ["end"] } });
    render(<Host initial={initial} captured={captured} />);
    await waitFor(() => expect(nodeElement("end")).toHaveClass("selected"));
    expect(nodeElement("start")).not.toHaveClass("selected");
    const callsAfterMount = captured.selections.length;
    // Let any feedback loop spin.
    await act(async () => { await new Promise((resolve) => setTimeout(resolve, 50)); });
    expect(captured.selections.length).toBeLessThanOrEqual(callsAfterMount + 1);
    expect(nodeElement("end")).toHaveClass("selected");
  });

  it("clears selection when the pane is clicked", async () => {
    const captured = emptyCaptured();
    render(<Host captured={captured} />);
    act(() => { fireEvent.click(nodeBody("start")!); });
    await waitFor(() => expect(nodeElement("start")).toHaveClass("selected"));
    act(() => { fireEvent.click(document.querySelector(".react-flow__pane")!); });
    await waitFor(() => expect(nodeElement("start")).not.toHaveClass("selected"));
    expect(captured.selections.at(-1)?.nodeIds).toEqual([]);
  });

  it("multi-selects nodes with ctrl-click and reports all selected ids", async () => {
    const captured = emptyCaptured();
    render(<Host captured={captured} />);
    // React Flow's multiSelectionKeyCode is Control (Meta on macOS; jsdom's
    // navigator is never macOS). Shift+click belongs to pane box selection.
    fireEvent.keyDown(window, { key: "Control", bubbles: true });
    act(() => {
      fireEvent.click(nodeBody("start")!, { ctrlKey: true });
      fireEvent.click(nodeBody("end")!, { ctrlKey: true });
    });
    fireEvent.keyUp(window, { key: "Control", bubbles: true });
    await waitFor(() => {
      expect(nodeElement("start")).toHaveClass("selected");
      expect(nodeElement("end")).toHaveClass("selected");
    });
    expect(captured.selections.at(-1)?.nodeIds).toEqual(["start", "end"]);
  });

  it("adds a node at the drop position when a palette drag is dropped on the canvas", async () => {
    const onDropNode = vi.fn();
    render(
      <Canvas
        state={baseState()}
        onPositionChange={vi.fn()}
        onSelectionChange={vi.fn()}
        onConnect={vi.fn()}
        onDeleteSelection={vi.fn()}
        onDropNode={onDropNode}
      />,
    );
    const surface = document.querySelector(".workflow-canvas") as HTMLElement;
    const dataTransfer = {
      types: [NODE_DRAG_MIME],
      getData: (mime: string) => (mime === NODE_DRAG_MIME ? "script" : ""),
      dropEffect: "none",
    };
    // Entering with a node-type payload marks the canvas as the drop target.
    fireEvent.dragEnter(surface, { dataTransfer });
    expect(surface).toHaveAttribute("data-dragover", "true");
    // dragOver must not be prevented for foreign payloads...
    fireEvent.dragOver(surface, { dataTransfer: { types: ["text/plain"], getData: () => "" }, clientX: 10, clientY: 10 });
    fireEvent.dragEnter(surface, { dataTransfer: { types: ["text/plain"], getData: () => "" } });
    // ...but our payload's dragOver enables the drop and the drop reports the
    // type plus a flow-space position.
    fireEvent.dragOver(surface, { dataTransfer, clientX: 120, clientY: 80 });
    fireEvent.drop(surface, { dataTransfer, clientX: 120, clientY: 80 });
    await waitFor(() => expect(onDropNode).toHaveBeenCalledTimes(1));
    expect(onDropNode).toHaveBeenCalledWith("script", expect.objectContaining({ x: expect.any(Number), y: expect.any(Number) }));
    // The drop ended the drag: the highlight clears.
    expect(surface).not.toHaveAttribute("data-dragover");
  });

  it("ignores drops that do not carry a known node type", async () => {
    const onDropNode = vi.fn();
    render(
      <Canvas
        state={baseState()}
        onPositionChange={vi.fn()}
        onSelectionChange={vi.fn()}
        onConnect={vi.fn()}
        onDeleteSelection={vi.fn()}
        onDropNode={onDropNode}
      />,
    );
    const surface = document.querySelector(".workflow-canvas") as HTMLElement;
    const dataTransfer = {
      types: [NODE_DRAG_MIME],
      getData: (mime: string) => (mime === NODE_DRAG_MIME ? "definitely-not-a-type" : ""),
      dropEffect: "none",
    };
    fireEvent.dragEnter(surface, { dataTransfer });
    fireEvent.dragOver(surface, { dataTransfer, clientX: 10, clientY: 10 });
    fireEvent.drop(surface, { dataTransfer, clientX: 10, clientY: 10 });
    expect(onDropNode).not.toHaveBeenCalled();
    expect(surface).not.toHaveAttribute("data-dragover");
  });
});

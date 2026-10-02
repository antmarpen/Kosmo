import { useCallback, useMemo, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { Background, Controls, Handle, Position, ReactFlow, type Connection, type Edge, type EdgeChange, type Node, type NodeChange, type NodeProps } from "@xyflow/react";
import "@xyflow/react/dist/style.css";
import type { WorkflowEdge, WorkflowEditorState, WorkflowNode } from "./model";

const visual: Record<WorkflowNode["type"], { icon: string; color: string }> = {
  start: { icon: "▶", color: "#16834a" }, script: { icon: "⌘", color: "#16834a" }, ai: { icon: "◆", color: "#2878c7" },
  http: { icon: "☁", color: "#c36a12" }, decision: { icon: "⑂", color: "#8156b3" }, workflow: { icon: "⧉", color: "#536b82" }, end: { icon: "■", color: "#b34444" },
};

function EditorNode({ data, selected }: NodeProps<Node<{ kind: WorkflowNode["type"] }>>) {
  const { t } = useTranslation();
  const kind = data.kind;
  const appearance = visual[kind];
  return <div className={`flex min-w-40 items-center gap-3 rounded-md border-2 bg-white px-3 py-3 text-sm shadow-sm ${selected ? "ring-2 ring-primary/25" : ""}`} style={{ borderColor: appearance.color }}>
    {kind !== "start" && <Handle type="target" position={Position.Left} className="!h-2.5 !w-2.5 !border-white !bg-slate-500" />}
    <span aria-hidden="true" className="text-lg leading-none" style={{ color: appearance.color }}>{appearance.icon}</span>
    <span className="font-medium">{t(`workflowEditor.types.${kind}`)}</span>
    {kind !== "end" && <Handle type="source" position={Position.Right} className="!h-2.5 !w-2.5 !border-white !bg-slate-500" />}
  </div>;
}

export const nodeVisuals = visual;
export const workflowNodeTypes = { workflowNode: EditorNode };

export type CanvasProps = {
  state: WorkflowEditorState;
  onPositionChange: (positions: Record<string, { x: number; y: number }>) => void;
  onSelectionChange: (nodeIds: string[], edge?: WorkflowEdge) => void;
  onConnect: (edge: WorkflowEdge) => void;
  onDeleteSelection: () => void;
};

type CanvasNode = Node<{ kind: WorkflowNode["type"] }>;

export function Canvas({ state, onPositionChange, onSelectionChange, onConnect, onDeleteSelection }: CanvasProps) {
  const { t } = useTranslation();
  const flow = useRef<{ fitView: () => void } | null>(null);
  const canvas = useRef<HTMLDivElement>(null);
  // Bumped when React Flow reports node dimensions so the nodes memo rebuilds
  // entries carrying the measured size; the following renders are idempotent.
  const [measuredTick, setMeasuredTick] = useState(0);

  // React Flow (v12) reuses a node's measured internals only while the node
  // object passed through the `nodes` prop keeps its reference identity
  // (adoptUserNodes with checkEquality). Recreating every object on every
  // editor update reset the internal `measured` and `selected` flags for the
  // whole graph, which surfaced as all-node flicker while dragging, selection
  // lost right after clicking, and dead edge selection. These caches keep one
  // object per id and rebuild an entry only when its position, kind, or
  // selected flag actually changed, so a drag frame replaces exactly one node
  // object and selection round-trips through editor state without churn.
  const nodeCache = useRef(new Map<string, CanvasNode>());
  const nodes = useMemo(() => {
    const selectedIds = new Set(state.selection.nodeIds);
    const nextCache = new Map<string, CanvasNode>();
    const result = state.definition.nodes.map((node): CanvasNode => {
      const position = state.layout.positions[node.id] ?? { x: 0, y: 0 };
      const selected = selectedIds.has(node.id);
      const cached = nodeCache.current.get(node.id);
      const entry = cached && cached.selected === selected && cached.data.kind === node.type && cached.position.x === position.x && cached.position.y === position.y
        ? cached
        : {
            id: node.id,
            type: "workflowNode",
            position,
            data: { kind: node.type },
            selected,
            // Measurement state recorded from dimension changes below; without
            // it every rebuilt node object resets RF's internal `measured`,
            // which renders the node hidden for a frame (visible flicker
            // while dragging).
            ...(cached?.measured ? { measured: cached.measured } : null),
            ...(cached?.width !== undefined ? { width: cached.width } : null),
            ...(cached?.height !== undefined ? { height: cached.height } : null),
          };
      nextCache.set(node.id, entry);
      return entry;
    });
    nodeCache.current = nextCache;
    return result;
  }, [state.definition.nodes, state.layout.positions, state.selection.nodeIds, measuredTick]);

  const edgeCache = useRef(new Map<string, Edge>());
  const edges = useMemo(() => {
    const selectedEdge = state.selection.edge;
    const nextCache = new Map<string, Edge>();
    const result = state.definition.edges.map((edge): Edge => {
      const id = `${edge.from}->${edge.to}`;
      const selected = !!selectedEdge && selectedEdge.from === edge.from && selectedEdge.to === edge.to;
      const cached = edgeCache.current.get(id);
      const entry = cached && cached.selected === selected ? cached : { id, source: edge.from, target: edge.to, type: "smoothstep", selected };
      nextCache.set(id, entry);
      return entry;
    });
    edgeCache.current = nextCache;
    return result;
  }, [state.definition.edges, state.selection.edge]);

  // Mirrors the committed editor selection so change handlers started in the
  // same event (node then edge changes) accumulate on the latest value instead
  // of a stale render-closure snapshot, and so redundant notifications collapse
  // before reaching editor state.
  const selectionRef = useRef(state.selection);
  selectionRef.current = state.selection;

  // The selection callbacks must keep a stable identity: React Flow
  // re-registers its selection listener whenever they change, and a
  // re-registered listener re-fires on every render with a store view that
  // lags the nodes prop by one commit, producing an alternating
  // select/deselect loop. Reading the prop through a ref keeps commitSelection
  // (and therefore mirrorSelection) referentially stable.
  const onSelectionChangeRef = useRef(onSelectionChange);
  onSelectionChangeRef.current = onSelectionChange;

  const commitSelection = useCallback((nodeIds?: string[], edge?: WorkflowEdge | null) => {
    const current = selectionRef.current;
    const next = {
      nodeIds: nodeIds ?? current.nodeIds,
      edge: edge === null ? undefined : edge ?? current.edge,
    };
    const sameNodes = current.nodeIds.length === next.nodeIds.length && current.nodeIds.every((id, index) => id === next.nodeIds[index]);
    const sameEdge = (current.edge === undefined && next.edge === undefined) || (current.edge !== undefined && next.edge !== undefined && current.edge.from === next.edge.from && current.edge.to === next.edge.to);
    if (sameNodes && sameEdge) return;
    selectionRef.current = next;
    onSelectionChangeRef.current(next.nodeIds, next.edge);
  }, []);

  // Controlled pattern: every change React Flow emits must be applied to the
  // state passed back through the nodes/edges props, otherwise the next
  // adoptUserNodes pass resets the internal flag (this is what made selection
  // and measurements churn before). Position changes go to the layout slice;
  // selection changes go to the selection slice; dimension changes update the
  // measured size carried on the cached node objects (the equivalent of
  // applyNodeChanges' handling). RF guarantees that selecting a node deselects
  // selected edges and vice versa by emitting the matching change type in the
  // same interaction, so each handler only writes its own slice. Removal
  // changes never occur here: deleteKeyCode is disabled and the editor deletes
  // through its own selection state instead.
  const handleNodesChange = useCallback((changes: NodeChange[]) => {
    let positions: Record<string, { x: number; y: number }> | null = null;
    let nodeIds: string[] | undefined;
    let measured = false;
    for (const change of changes) {
      if (change.type === "position" && "position" in change && change.position) {
        positions ??= { ...state.layout.positions };
        positions[change.id] = change.position;
      } else if (change.type === "select") {
        nodeIds ??= [...selectionRef.current.nodeIds];
        if (change.selected) {
          if (!nodeIds.includes(change.id)) nodeIds.push(change.id);
        } else {
          nodeIds = nodeIds.filter((id) => id !== change.id);
        }
      } else if (change.type === "dimensions" && "dimensions" in change && change.dimensions) {
        const cached = nodeCache.current.get(change.id);
        if (cached) {
          const entry: CanvasNode = { ...cached, measured: { ...change.dimensions } };
          if (change.setAttributes === true) {
            entry.width = change.dimensions.width;
            entry.height = change.dimensions.height;
          } else if (change.setAttributes === "width") {
            entry.width = change.dimensions.width;
          } else if (change.setAttributes === "height") {
            entry.height = change.dimensions.height;
          }
          nodeCache.current.set(change.id, entry);
        }
        measured = true;
      }
    }
    if (positions) onPositionChange(positions);
    if (nodeIds) commitSelection(nodeIds);
    if (measured) setMeasuredTick((tick) => tick + 1);
  }, [commitSelection, onPositionChange, state.layout.positions]);

  const handleEdgesChange = useCallback((changes: EdgeChange[]) => {
    let edge: WorkflowEdge | null | undefined;
    for (const change of changes) {
      if (change.type === "select") {
        const [from, to] = change.id.split("->");
        if (!from || !to) continue;
        edge = change.selected ? { from, to } : null;
      }
    }
    if (edge !== undefined) commitSelection(undefined, edge);
  }, [commitSelection]);

  const handleConnect = useCallback((connection: Connection) => {
    if (!connection.source || !connection.target || connection.source === connection.target) return;
    const source = state.definition.nodes.find((node) => node.id === connection.source);
    const target = state.definition.nodes.find((node) => node.id === connection.target);
    if (!source || !target || source.type === "end" || target.type === "start") return;
    onConnect({ from: source.id, to: target.id });
  }, [onConnect, state.definition.nodes]);

  // React Flow's selection listener reports the store's selected sets after
  // each real transition; stable identity (via commitSelection) keeps this
  // from re-firing per render, and commitSelection makes it idempotent with
  // the change handlers above.
  const mirrorSelection = useCallback(({ nodes: selectedNodes, edges: selectedEdges }: { nodes: { id: string }[]; edges: { source: string; target: string }[] }) => {
    commitSelection(selectedNodes.map((node) => node.id), selectedEdges[0] ? { from: selectedEdges[0].source, to: selectedEdges[0].target } : null);
  }, [commitSelection]);

  return <div ref={canvas} className="workflow-canvas relative min-h-0 flex-1" onKeyDown={(event) => { if (event.key === "Delete" || event.key === "Backspace") { event.preventDefault(); onDeleteSelection(); } }} tabIndex={0} aria-label={t("workflowEditor.canvas")}>
    <ReactFlow nodes={nodes} edges={edges} nodeTypes={workflowNodeTypes} onNodesChange={handleNodesChange} onEdgesChange={handleEdgesChange} onConnect={handleConnect} onSelectionChange={mirrorSelection} onInit={(instance) => { flow.current = instance; }} onNodeClick={() => canvas.current?.focus()} onPaneClick={() => commitSelection([], null)} fitView deleteKeyCode={null} nodesDraggable nodesConnectable elementsSelectable>
      <Background color="#aab7c4" gap={22} size={1} /><Controls />
    </ReactFlow>
    <button type="button" className="absolute bottom-3 right-3 z-10 rounded-full border border-border bg-background px-3 py-2 text-xs font-medium hover:bg-muted focus-visible:outline-2 focus-visible:outline-ring" onClick={() => flow.current?.fitView()}>{t("workflowEditor.fitView")}</button>
  </div>;
}

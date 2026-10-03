import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes, useLocation } from "react-router";
import { beforeEach, describe, expect, it, vi } from "vitest";
import i18next from "i18next";
import { NODE_DRAG_MIME } from "./Canvas";
import { createNode } from "./nodeDefaults";

const { get, post, put } = vi.hoisted(() => ({ get: vi.fn(), post: vi.fn(), put: vi.fn() }));
vi.mock("@/api/auth", () => ({ api: { GET: get, POST: post, PUT: put } }));

import { EditorPage } from "./EditorPage";

/** Resolves through i18next so assertions hold both before and after the pending catalog keys land. */
const catalogText = (key: string, params?: Record<string, unknown>) => String(i18next.t(key as never, params as never));

vi.mock("@xyflow/react", async () => {
  const React = await import("react");
  return {
    ReactFlow: (props: any) => React.createElement("div", { "data-testid": "flow" },
      ...props.nodes.map((node: any) => React.createElement("div", { key: node.id }, React.createElement(props.nodeTypes[node.type], { id: node.id, data: node.data, selected: node.selected }))),
      React.createElement("button", { onClick: () => props.onConnect({ source: "start", target: "end" }) }, "connect valid"),
      React.createElement("button", { onClick: () => props.onConnect({ source: "end", target: "start" }) }, "connect invalid"),
      React.createElement("button", { onClick: () => props.onNodesChange([{ type: "position", id: "start", position: { x: 42, y: 84 } }]) }, "move start"),
      React.createElement("button", { onClick: () => props.onSelectionChange({ nodes: [{ id: "start" }], edges: [] }) }, "select start"),
      React.createElement("button", { onClick: () => props.onSelectionChange({ nodes: [{ id: "end" }], edges: [] }) }, "select end"),
      React.createElement("button", { onClick: () => props.onSelectionChange({ nodes: [], edges: [] }) }, "clear selection")),
    Handle: () => null, Position: { Left: "left", Right: "right" }, Background: () => null, Controls: () => null,
    addEdge: (edge: any, edges: any[]) => [...edges, edge],
  };
});

/**
 * Exact backend contracts (backend/app/api/routes/workflows.py):
 * - GET /workflows/{workflow_id}/drafts/{draft_id} → WorkflowDraftResponse {id, revision, definition, layout}
 * - GET /workflows/{workflow_id}/drafts → WorkflowDraftMetadata[]
 * - POST /workflows/{workflow_id}/drafts → 201 {draft_id, revision}
 * - PUT /workflows/{workflow_id}/drafts/{draft_id}?validate= → {revision, issues?}
 * - GET /workflows/{workflow_id} → WorkflowResponse {id, name, publication_revision, active_version}
 * - GET /workflows/{workflow_id}/versions → WorkflowVersionSummary[] {id, version, published_at, is_active}
 * - POST /workflows/{workflow_id}/drafts/{draft_id}/publish → 201 WorkflowVersionResponse
 * - POST /workflows/{workflow_id}/activate → {version_id, active_revision}
 */
const baseDefinition = {
  schema_version: "v1" as const,
  name: "Sample workflow",
  nodes: [createNode("start", "start"), createNode("end", "end")],
  edges: [],
};
const draftResponse = { id: "draft-1", revision: 1, definition: baseDefinition, layout: { positions: {}, viewport: { x: 0, y: 0, zoom: 1 } } };
/** A definition the client-side validation accepts (end reachable from start). */
const validDefinition = { ...baseDefinition, edges: [{ from: "start", to: "end" }] };
const workflowPath = "/workflows/{workflow_id}";
const versionsPath = "/workflows/{workflow_id}/versions";
const publishPath = "/workflows/{workflow_id}/drafts/{draft_id}/publish";
const activatePath = "/workflows/{workflow_id}/activate";
const workflowResponse = { id: "wf-1", name: "Sample workflow", publication_revision: 2, active_version: { id: "wf-1:3", version: 3, definition: {} } };
const publishResponse = { id: "wf-1:4", workflow_id: "wf-1", version: 4, definition: {} };
/** GET /workflows/{workflow_id}/versions → WorkflowVersionSummary[] (metadata only, newest first). */
const versionsResponse = [
  { id: "wf-1:3", version: 3, published_at: "2026-10-01T00:00:00Z", is_active: true },
];

function LocationProbe() {
  const location = useLocation();
  return <div data-testid="location">{location.pathname}{location.search}</div>;
}

function renderPage(entry = "/workflows/wf-1/edit?draftId=draft-1") {
  return render(<MemoryRouter initialEntries={[entry]}><Routes>
    <Route path="/workflows/:id/edit" element={<><EditorPage /><LocationProbe /></>} />
  </Routes></MemoryRouter>);
}

/** Routes the GET mock by endpoint path, as openapi-fetch does. */
function mockGets(overrides: Record<string, unknown> = {}) {
  get.mockImplementation((path: string) => {
    if (path in overrides) return Promise.resolve(overrides[path]);
    if (path === "/workflows/{workflow_id}/drafts/{draft_id}") return Promise.resolve({ data: draftResponse });
    if (path === "/workflows/{workflow_id}/drafts") return Promise.resolve({ data: [{ id: "draft-1", revision: 1, updated_at: "2026-10-01T00:00:00Z" }] });
    if (path === workflowPath) return Promise.resolve({ data: workflowResponse });
    if (path === versionsPath) return Promise.resolve({ data: versionsResponse });
    return Promise.resolve({ data: null });
  });
}

/** Publish/activate POSTs the editor can make, routed by endpoint path. */
function mockPosts() {
  post.mockImplementation((path: string) => {
    if (path === "/workflows/{workflow_id}/drafts") return Promise.resolve({ data: { draft_id: "draft-new", revision: 1 } });
    if (path === publishPath) return Promise.resolve({ data: publishResponse });
    if (path === activatePath) return Promise.resolve({ data: { version_id: "wf-1:3", active_revision: 3 } });
    return Promise.resolve({ data: null });
  });
}

const kosmoConflict = (message_key: string, params: Record<string, unknown>) => ({ error: { code: "CONFLICT", message_key, params, details: [] } });

function callsTo(path: string) {
  return post.mock.calls.filter(([called]) => called === path);
}

describe("workflow editor page", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockGets();
    mockPosts();
    put.mockResolvedValue({ data: { revision: 2, issues: [] } });
  });

  it("renders all seven node types with their approved icons", async () => {
    renderPage();
    await screen.findByTestId("flow");
    for (const icon of ["▶", "⌘", "◆", "☁", "⑂", "⧉", "■"]) expect(screen.getAllByText(icon).length).toBeGreaterThan(0);
  });

  it("loads the saved draft definition and layout into the canvas", async () => {
    mockGets({ "/workflows/{workflow_id}/drafts/{draft_id}": { data: {
      id: "draft-1",
      revision: 4,
      definition: { ...baseDefinition, nodes: [createNode("start", "start"), createNode("script", "script"), createNode("end", "end")], edges: [{ from: "start", to: "script" }, { from: "script", to: "end" }] },
      layout: { positions: { script: { x: 320, y: 140 } }, viewport: { x: 0, y: 0, zoom: 1 } },
    } } });
    renderPage();

    expect(await screen.findByText("3 nodes")).toBeInTheDocument();
    expect(screen.getByText("Revision 4")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "select start" }));
    expect(get).toHaveBeenCalledWith("/workflows/{workflow_id}/drafts/{draft_id}", { params: { path: { workflow_id: "wf-1", draft_id: "draft-1" } } });
  });

  it("dispatches add-node and delete operations against editor state", async () => {
    renderPage();
    await screen.findByTestId("flow");
    fireEvent.click(screen.getByRole("button", { name: "Add Script" }));
    expect(screen.getByText("3 nodes")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Delete selection" }));
    expect(screen.getByText("2 nodes")).toBeInTheDocument();
  });

  it("accepts valid connections and rejects Start incoming and End outgoing connections", async () => {
    renderPage();
    await screen.findByTestId("flow");
    fireEvent.click(screen.getByRole("button", { name: "connect valid" }));
    expect(screen.getByTestId("connection-count")).toHaveTextContent("1 connection");
    fireEvent.click(screen.getByRole("button", { name: "connect invalid" }));
    expect(screen.getByTestId("connection-count")).toHaveTextContent("1 connection");
  });

  it("preserves fixed structural nodes and their incident edges when deletion is requested", async () => {
    renderPage();
    await screen.findByTestId("flow");
    fireEvent.click(screen.getByRole("button", { name: "connect valid" }));
    fireEvent.click(screen.getByRole("button", { name: "select end" }));
    expect(screen.queryByRole("button", { name: "Delete selection" })).not.toBeInTheDocument();
    expect(screen.getByText("2 nodes")).toBeInTheDocument();
    expect(screen.getByTestId("connection-count")).toHaveTextContent("1 connection");
  });

  it("hides Delete selection for Start and End but keeps it for ordinary nodes", async () => {
    mockGets({ "/workflows/{workflow_id}/drafts/{draft_id}": { data: { ...draftResponse, definition: { ...baseDefinition, nodes: [createNode("start", "start"), createNode("script", "script"), createNode("end", "end")] } } } });
    renderPage();
    await screen.findByTestId("flow");
    fireEvent.click(screen.getByRole("button", { name: "select start" }));
    expect(screen.queryByRole("button", { name: "Delete selection" })).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "select end" }));
    expect(screen.queryByRole("button", { name: "Delete selection" })).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "clear selection" }));
    fireEvent.click(screen.getByRole("button", { name: "Add Script" }));
    expect(screen.getByRole("button", { name: "Delete selection" })).toBeInTheDocument();
  });

  it("syncs node positions to editor layout state", async () => {
    renderPage();
    await screen.findByTestId("flow");
    fireEvent.click(screen.getByRole("button", { name: "select start" }));
    fireEvent.click(screen.getByRole("button", { name: "move start" }));
    expect(screen.getByText("42, 84")).toBeInTheDocument();
  });

  it("saves the full definition and layout with the loaded revision as the expected revision", async () => {
    renderPage();
    await screen.findByTestId("flow");
    fireEvent.click(screen.getByRole("button", { name: "Add Script" }));
    fireEvent.click(screen.getByRole("button", { name: "Save draft" }));

    await waitFor(() => expect(put).toHaveBeenCalledTimes(1));
    const [path, options] = put.mock.calls[0] as [string, { params: unknown; body: any }];
    expect(path).toBe("/workflows/{workflow_id}/drafts/{draft_id}");
    expect(options.params).toEqual({ path: { workflow_id: "wf-1", draft_id: "draft-1" }, query: { validate: true } });
    expect(options.body.expected_revision).toBe(1);
    expect(options.body.definition.nodes).toHaveLength(3);
    expect(options.body.layout).toHaveProperty("positions");
    expect(await screen.findByText("Revision 2")).toBeInTheDocument();
    expect(screen.getByText("Saved")).toBeInTheDocument();
  });

  it("saves an edited workflow name through the draft save contract", async () => {
    renderPage();
    const nameField = await screen.findByLabelText(catalogText("workflowEditor.nameLabel"));
    expect(nameField).toHaveValue("Sample workflow");
    fireEvent.change(nameField, { target: { value: "Renamed workflow" } });
    fireEvent.click(screen.getByRole("button", { name: "Save draft" }));

    await waitFor(() => expect(put).toHaveBeenCalledTimes(1));
    const [, options] = put.mock.calls[0] as [string, { body: { definition: { name: string } } }];
    expect(options.body.definition.name).toBe("Renamed workflow");
    expect(await screen.findByText("Saved")).toBeInTheDocument();
  });

  it("falls back to the blank start/end seed when a draft has no usable definition", async () => {
    mockGets({ "/workflows/{workflow_id}/drafts/{draft_id}": { data: { id: "draft-1", revision: 1, definition: {}, layout: {} } } });
    renderPage();
    expect(await screen.findByText("2 nodes")).toBeInTheDocument();
    expect(screen.getByTestId("flow")).toBeInTheDocument();
  });

  it("seeds a blank draft with the workflow's own name instead of Untitled workflow", async () => {
    // A workflow created as "Quarterly review" seeds its draft as {}; the
    // editor must show the collected name, never the "Untitled workflow"
    // placeholder that publishing would silently rename the workflow to.
    mockGets({
      "/workflows/{workflow_id}/drafts/{draft_id}": { data: { id: "draft-1", revision: 1, definition: {}, layout: {} } },
      [workflowPath]: { data: { id: "wf-1", name: "Quarterly review", publication_revision: 0, active_version: null } },
    });
    renderPage();

    const nameField = await screen.findByLabelText(catalogText("workflowEditor.nameLabel"));
    expect(nameField).toHaveValue("Quarterly review");
    expect(screen.queryByDisplayValue("Untitled workflow")).not.toBeInTheDocument();
  });

  it("carries the workflow's collected name through save and publish", async () => {
    // Blank seed + the collected name: connecting the graph makes the draft
    // publishable, so publishing saves first and both requests must carry
    // the workflow's name — publishing never renames it to a placeholder.
    mockGets({
      "/workflows/{workflow_id}/drafts/{draft_id}": { data: { id: "draft-1", revision: 1, definition: {}, layout: {} } },
      [workflowPath]: { data: { id: "wf-1", name: "Quarterly review", publication_revision: 0, active_version: null } },
    });
    renderPage();
    await screen.findByTestId("flow");
    fireEvent.click(screen.getByRole("button", { name: "connect valid" }));
    fireEvent.click(screen.getByRole("button", { name: /publish/i }));

    await waitFor(() => expect(put).toHaveBeenCalledTimes(1));
    const [, saveOptions] = put.mock.calls[0] as [string, { body: { definition: { name: string } } }];
    expect(saveOptions.body.definition.name).toBe("Quarterly review");
    await waitFor(() => expect(callsTo(publishPath)).toHaveLength(1));
    const notice = await screen.findByTestId("editor-notice");
    expect(notice).toHaveAttribute("data-key", "workflowEditor.publishSuccess");
  });

  it("creates a draft when the editor opens an existing workflow without one", async () => {
    get.mockImplementation((path: string) => {
      if (path === "/workflows/{workflow_id}/drafts") return Promise.resolve({ data: [] });
      if (path === workflowPath) return Promise.resolve({ data: workflowResponse });
      if (path === "/workflows/{workflow_id}/drafts/{draft_id}") return Promise.resolve({ data: { ...draftResponse, id: "draft-new" } });
      return Promise.resolve({ data: null });
    });
    renderPage("/workflows/wf-1/edit");
    await screen.findByTestId("flow");

    expect(post).toHaveBeenCalledWith("/workflows/{workflow_id}/drafts", { params: { path: { workflow_id: "wf-1" } } });
    await waitFor(() => expect(screen.getByTestId("location")).toHaveTextContent("draftId=draft-new"));
  });

  it("keeps the node-properties sheet reachable below the side-panel breakpoint", async () => {
    renderPage();
    await screen.findByTestId("flow");
    const propertiesToggle = screen.getByRole("button", { name: "Node properties" });
    const paletteToggle = screen.getByRole("button", { name: "Add node" });
    // Nothing is selected yet: the panel has nothing to show, so the toggle
    // is disabled instead of revealing an empty sheet.
    expect(propertiesToggle).toBeDisabled();
    // Selecting a node opens the properties sheet so it is immediately editable.
    fireEvent.click(screen.getByRole("button", { name: "select start" }));
    expect(propertiesToggle).toBeEnabled();
    expect(propertiesToggle).toHaveAttribute("aria-expanded", "true");
    // The two sheets are mutually exclusive so neither can cover the other.
    fireEvent.click(paletteToggle);
    expect(paletteToggle).toHaveAttribute("aria-expanded", "true");
    expect(propertiesToggle).toHaveAttribute("aria-expanded", "false");
    fireEvent.click(propertiesToggle);
    expect(propertiesToggle).toHaveAttribute("aria-expanded", "true");
    expect(paletteToggle).toHaveAttribute("aria-expanded", "false");
    fireEvent.click(propertiesToggle);
    expect(propertiesToggle).toHaveAttribute("aria-expanded", "false");
  });

  it("renders the properties panel only while a node is selected", async () => {
    renderPage();
    await screen.findByTestId("flow");
    // No selection: the desktop panel is not rendered at all.
    expect(screen.queryByRole("complementary", { name: "Node properties" })).not.toBeInTheDocument();
    // Selecting a node surfaces the panel with that node's content...
    fireEvent.click(screen.getByRole("button", { name: "select start" }));
    expect(screen.getByRole("heading", { name: "Node properties: Start" })).toBeInTheDocument();
    // ...selecting another node swaps it...
    fireEvent.click(screen.getByRole("button", { name: "select end" }));
    expect(screen.getByRole("heading", { name: "Node properties: End" })).toBeInTheDocument();
    // ...and clicking the canvas pane clears the selection and closes the panel.
    fireEvent.click(screen.getByRole("button", { name: "clear selection" }));
    expect(screen.queryByRole("complementary", { name: "Node properties" })).not.toBeInTheDocument();
  });

  it("filters the node catalog from the search field and reports when nothing matches", async () => {
    renderPage();
    await screen.findByTestId("flow");
    const palette = screen.getByRole("complementary", { name: "Node types" });
    const search = screen.getByRole("searchbox", { name: "Search node types" });
    await userEvent.type(search, "script");
    expect(within(palette).getByRole("button", { name: "Add Script" })).toBeInTheDocument();
    expect(within(palette).queryByRole("button", { name: "Add Start" })).not.toBeInTheDocument();
    // A query nothing matches keeps the search honest instead of silently
    // hiding the catalog.
    await userEvent.clear(search);
    await userEvent.type(search, "zzz");
    expect(within(palette).queryByRole("button", { name: /^Add/ })).not.toBeInTheDocument();
    expect(within(palette).getByText(/No node types match/)).toBeInTheDocument();
    // Clearing the query restores the full catalog.
    await userEvent.clear(search);
    expect(within(palette).queryByRole("button", { name: "Add Start" })).not.toBeInTheDocument();
    expect(within(palette).queryByRole("button", { name: "Add End" })).not.toBeInTheDocument();
  });

  it("describes each catalog entry under its type name", async () => {
    renderPage();
    await screen.findByTestId("flow");
    const palette = screen.getByRole("complementary", { name: "Node types" });
    expect(within(palette).getByText("Run a Python script in an isolated sandbox.")).toBeInTheDocument();
    expect(within(palette).getByText("Delegate a step to an AI agent.")).toBeInTheDocument();
  });

  it("starts a palette drag carrying the node type for the canvas drop", async () => {
    renderPage();
    await screen.findByTestId("flow");
    const setData = vi.fn();
    const button = screen.getByRole("button", { name: "Add Script" });
    fireEvent.dragStart(button, { dataTransfer: { setData, effectAllowed: "" } });
    expect(button).toHaveAttribute("draggable", "true");
    expect(setData).toHaveBeenCalledWith(NODE_DRAG_MIME, "script");
  });

  it("renders flat backend API errors through the Kosmo error alert", async () => {
    mockGets({ "/workflows/{workflow_id}/drafts/{draft_id}": { error: { code: "NOT_FOUND", message_key: "errors.workflow.draft_not_found", params: {}, details: [] } } });
    renderPage();
    expect(await screen.findByRole("alert")).toHaveTextContent("Draft not found.");
    expect(screen.queryByTestId("flow")).not.toBeInTheDocument();
  });

  it("blocks publishing with an explanation while the draft fails validation", async () => {
    renderPage();
    await screen.findByTestId("flow");
    fireEvent.click(screen.getByRole("button", { name: /publish/i }));

    expect(await screen.findByTestId("publish-blocked")).toBeInTheDocument();
    expect(screen.getByTestId("publish-blocked")).toHaveTextContent(catalogText("workflowEditor.validation.noReachableEnd"));
    expect(post).not.toHaveBeenCalled();
  });

  it("publishes with the publication revision and shows the new version", async () => {
    mockGets({
      "/workflows/{workflow_id}/drafts/{draft_id}": { data: { ...draftResponse, definition: validDefinition } },
      [versionsPath]: { data: [
        { id: "wf-1:4", version: 4, published_at: "2026-10-02T00:00:00Z", is_active: false },
        { id: "wf-1:3", version: 3, published_at: "2026-10-01T00:00:00Z", is_active: true },
      ] },
    });
    renderPage();
    await screen.findByTestId("flow");
    fireEvent.click(screen.getByRole("button", { name: /publish/i }));

    await waitFor(() => expect(callsTo(publishPath)).toHaveLength(1));
    expect(post).toHaveBeenCalledWith(publishPath, {
      params: { path: { workflow_id: "wf-1", draft_id: "draft-1" } },
      body: { expected_pub_revision: 2, confirm_overwrite: false },
    });
    const notice = await screen.findByTestId("editor-notice");
    expect(notice).toHaveAttribute("data-key", "workflowEditor.publishSuccess");
    expect(notice).toHaveAttribute("data-version", "4");
    // The workflow state was refreshed after publishing so the next publish
    // attempt uses the incremented publication revision.
    const workflowLoads = get.mock.calls.filter(([path]) => path === workflowPath);
    expect(workflowLoads.length).toBeGreaterThanOrEqual(2);
    const publishOrder = post.mock.invocationCallOrder.find((_order, index) => post.mock.calls[index]?.[0] === publishPath);
    expect(publishOrder).toBeLessThan(get.mock.invocationCallOrder[get.mock.invocationCallOrder.length - 1]);
    // The just-published version becomes the default activation choice.
    fireEvent.click(screen.getByRole("button", { name: /activate/i }));
    const dialog = await screen.findByRole("dialog");
    expect(within(dialog).getByLabelText(/published version/i)).toHaveValue("wf-1:4");
  });

  it("publishes without touching the active version while the activate option stays off", async () => {
    mockGets({ "/workflows/{workflow_id}/drafts/{draft_id}": { data: { ...draftResponse, definition: validDefinition } } });
    renderPage();
    await screen.findByTestId("flow");
    // Spec AC-P2-06: the option is off by default; publishing alone changes nothing.
    expect(screen.getByRole("checkbox", { name: catalogText("workflowEditor.activateAfterPublish") })).not.toBeChecked();
    fireEvent.click(screen.getByRole("button", { name: /publish/i }));

    const notice = await screen.findByTestId("editor-notice");
    expect(notice).toHaveAttribute("data-key", "workflowEditor.publishSuccess");
    expect(callsTo(activatePath)).toHaveLength(0);
  });

  it("activates the just-published version as a separate request when the activate option is checked", async () => {
    mockGets({ "/workflows/{workflow_id}/drafts/{draft_id}": { data: { ...draftResponse, definition: validDefinition } } });
    renderPage();
    await screen.findByTestId("flow");
    fireEvent.click(screen.getByRole("checkbox", { name: catalogText("workflowEditor.activateAfterPublish") }));
    fireEvent.click(screen.getByRole("button", { name: /publish/i }));

    await waitFor(() => expect(callsTo(activatePath)).toHaveLength(1));
    expect(post).toHaveBeenCalledWith(activatePath, {
      params: { path: { workflow_id: "wf-1" } },
      body: { version_id: "wf-1:4", expected_active_revision: 3, confirm_stale_base: false },
    });
    const notices = await screen.findAllByTestId("editor-notice");
    expect(notices.map((notice) => notice.getAttribute("data-key"))).toEqual(["workflowEditor.publishSuccess", "workflowEditor.activateSuccess"]);
  });

  it("offers every published version after a reload and marks the active one", async () => {
    mockGets({ [versionsPath]: { data: [
      { id: "wf-1:2", version: 2, published_at: "2026-09-30T00:00:00Z", is_active: false },
      { id: "wf-1:3", version: 3, published_at: "2026-10-01T00:00:00Z", is_active: true },
    ] } });
    renderPage();
    await screen.findByTestId("flow");
    fireEvent.click(screen.getByRole("button", { name: /activate/i }));

    const dialog = await screen.findByRole("dialog");
    const select = within(dialog).getByLabelText(/published version/i);
    // A previously published inactive version is selectable after a reload;
    // the active one is marked and preselected when nothing was just published.
    expect(within(select).getByRole("option", { name: "Version 2" })).toBeInTheDocument();
    expect(within(select).getByRole("option", { name: catalogText("workflowEditor.activateOptionActive", { version: 3 }) })).toBeInTheDocument();
    expect(select).toHaveValue("wf-1:3");
    fireEvent.change(select, { target: { value: "wf-1:2" } });
    fireEvent.click(within(dialog).getByRole("button", { name: "Confirm" }));

    await waitFor(() => expect(callsTo(activatePath)).toHaveLength(1));
    expect(callsTo(activatePath)[0]?.[1]?.body).toEqual({ version_id: "wf-1:2", expected_active_revision: 3, confirm_stale_base: false });
  });

  it("defaults the picker to the newest version when nothing is active after a reload", async () => {
    // Publishing without activating, then reloading, leaves no active version
    // and no just-published one: the newest candidate must still be selectable
    // and the confirm action operable (AR-02).
    mockGets({
      [workflowPath]: { data: { ...workflowResponse, active_version: null } },
      [versionsPath]: { data: [
        { id: "wf-1:1", version: 1, published_at: "2026-10-01T00:00:00Z", is_active: false },
      ] },
    });
    renderPage();
    await screen.findByTestId("flow");
    fireEvent.click(screen.getByRole("button", { name: /activate/i }));

    const dialog = await screen.findByRole("dialog");
    const select = within(dialog).getByLabelText(/published version/i);
    expect(select).toHaveValue("wf-1:1");
    const confirm = within(dialog).getByRole("button", { name: "Confirm" });
    expect(confirm).toBeEnabled();
    fireEvent.click(confirm);

    await waitFor(() => expect(callsTo(activatePath)).toHaveLength(1));
    expect(callsTo(activatePath)[0]?.[1]?.body).toEqual({ version_id: "wf-1:1", expected_active_revision: 0, confirm_stale_base: false });
  });

  it("requests the picker's first version page with limit and offset", async () => {
    renderPage();
    await screen.findByTestId("flow");
    fireEvent.click(screen.getByRole("button", { name: /activate/i }));
    await screen.findByRole("dialog");

    const versionsCalls = get.mock.calls.filter(([path]) => path === versionsPath);
    expect(versionsCalls).toHaveLength(1);
    const [, options] = versionsCalls[0] as [string, { params: { query: { limit: number; offset: number } } }];
    expect(options.params.query).toEqual({ limit: 50, offset: 0 });
  });

  it("appends the next version page via load more and hides the control when pages end", async () => {
    // A full first page (versions 51..2) means more pages exist; the next
    // page comes back short (only version 1), which is the end of the list.
    const firstPage = Array.from({ length: 50 }, (_, index) => ({
      id: `wf-1:${51 - index}`, version: 51 - index, published_at: "2026-10-01T00:00:00Z", is_active: false,
    }));
    const secondPage = [{ id: "wf-1:1", version: 1, published_at: "2026-09-30T00:00:00Z", is_active: false }];
    get.mockImplementation((path: string, options?: { params?: { query?: { offset?: number } } }) => {
      if (path === versionsPath) {
        const offset = options?.params?.query?.offset ?? 0;
        return Promise.resolve({ data: offset === 0 ? firstPage : secondPage });
      }
      if (path === "/workflows/{workflow_id}/drafts/{draft_id}") return Promise.resolve({ data: draftResponse });
      if (path === "/workflows/{workflow_id}/drafts") return Promise.resolve({ data: [{ id: "draft-1", revision: 1, updated_at: "2026-10-01T00:00:00Z" }] });
      if (path === workflowPath) return Promise.resolve({ data: workflowResponse });
      return Promise.resolve({ data: null });
    });
    renderPage();
    await screen.findByTestId("flow");
    fireEvent.click(screen.getByRole("button", { name: /activate/i }));
    const dialog = await screen.findByRole("dialog");
    const select = within(dialog).getByLabelText(/published version/i);
    // Only the first page is listed before loading more.
    expect(within(select).getByRole("option", { name: "Version 2" })).toBeInTheDocument();
    expect(within(select).queryByRole("option", { name: "Version 1" })).not.toBeInTheDocument();

    await userEvent.click(within(dialog).getByRole("button", { name: catalogText("workflowEditor.activateLoadMore") }));

    // The next request walks the accumulated offset...
    await waitFor(() => expect(get).toHaveBeenCalledWith(versionsPath, { params: { path: { workflow_id: "wf-1" }, query: { limit: 50, offset: 50 } } }));
    // ...its versions are appended to the same picker...
    expect(within(select).getByRole("option", { name: "Version 1" })).toBeInTheDocument();
    expect(within(select).getAllByRole("option")).toHaveLength(51);
    // ...and the control disappears: a short page means no more versions.
    expect(within(dialog).queryByRole("button", { name: catalogText("workflowEditor.activateLoadMore") })).not.toBeInTheDocument();
  });

  it("hides the load-more control when the first version page is short", async () => {
    renderPage();
    await screen.findByTestId("flow");
    fireEvent.click(screen.getByRole("button", { name: /activate/i }));
    const dialog = await screen.findByRole("dialog");
    expect(within(dialog).getByLabelText(/published version/i)).toBeInTheDocument();
    expect(within(dialog).queryByRole("button", { name: catalogText("workflowEditor.activateLoadMore") })).not.toBeInTheDocument();
  });

  it("saves unsaved changes before publishing them", async () => {
    mockGets({ "/workflows/{workflow_id}/drafts/{draft_id}": { data: { ...draftResponse, definition: validDefinition } } });
    renderPage();
    await screen.findByTestId("flow");
    fireEvent.click(screen.getByRole("button", { name: "select start" }));
    fireEvent.click(screen.getByRole("button", { name: "move start" }));
    fireEvent.click(screen.getByRole("button", { name: /publish/i }));

    await waitFor(() => expect(callsTo(publishPath)).toHaveLength(1));
    expect(put).toHaveBeenCalledTimes(1);
    expect(put.mock.invocationCallOrder[0]).toBeLessThan(post.mock.invocationCallOrder[0]);
  });

  it("adopts the returned publication revision and retries after a conflict", async () => {
    mockGets({ "/workflows/{workflow_id}/drafts/{draft_id}": { data: { ...draftResponse, definition: validDefinition } } });
    post.mockImplementationOnce(() => Promise.resolve(kosmoConflict("errors.workflow.publication_revision_conflict", { current_revision: 5 })));
    post.mockImplementationOnce(() => Promise.resolve({ data: publishResponse }));
    renderPage();
    await screen.findByTestId("flow");
    fireEvent.click(screen.getByRole("button", { name: /publish/i }));

    await waitFor(() => expect(callsTo(publishPath)).toHaveLength(2));
    expect(callsTo(publishPath)[1]?.[1]?.body).toEqual({ expected_pub_revision: 5, confirm_overwrite: false });
    expect(screen.getAllByTestId("editor-notice").map((notice) => notice.getAttribute("data-key")))
      .toEqual(["workflowEditor.publishWorkflowChanged", "workflowEditor.publishSuccess"]);
  });

  it("requires explicit confirmation when someone published recently", async () => {
    mockGets({ "/workflows/{workflow_id}/drafts/{draft_id}": { data: { ...draftResponse, definition: validDefinition } } });
    post.mockImplementationOnce(() => Promise.resolve(kosmoConflict("errors.workflow.publication_confirmation_required", { publication_revision: 2 })));
    post.mockImplementationOnce(() => Promise.resolve({ data: publishResponse }));
    renderPage();
    await screen.findByTestId("flow");
    fireEvent.click(screen.getByRole("button", { name: /publish/i }));

    const dialog = await screen.findByRole("alertdialog");
    fireEvent.click(within(dialog).getByRole("button", { name: /anyway/i }));

    await waitFor(() => expect(callsTo(publishPath)).toHaveLength(2));
    expect(callsTo(publishPath)[1]?.[1]?.body).toEqual({ expected_pub_revision: 2, confirm_overwrite: true });
    expect(await screen.findByTestId("editor-notice")).toHaveAttribute("data-key", "workflowEditor.publishSuccess");
  });

  it("requires explicit confirmation before publishing from a stale base", async () => {
    mockGets({ "/workflows/{workflow_id}/drafts/{draft_id}": { data: { ...draftResponse, definition: validDefinition } } });
    post.mockImplementationOnce(() => Promise.resolve(kosmoConflict("errors.workflow.stale_base_confirmation_required", { active_version_id: "wf-1:3" })));
    post.mockImplementationOnce(() => Promise.resolve({ data: publishResponse }));
    renderPage();
    await screen.findByTestId("flow");
    fireEvent.click(screen.getByRole("button", { name: /publish/i }));

    const dialog = await screen.findByRole("alertdialog");
    fireEvent.click(within(dialog).getByRole("button", { name: /anyway/i }));

    await waitFor(() => expect(callsTo(publishPath)).toHaveLength(2));
    expect(callsTo(publishPath)[1]?.[1]?.body).toEqual({ expected_pub_revision: 2, confirm_overwrite: true });
    expect(await screen.findByTestId("editor-notice")).toHaveAttribute("data-key", "workflowEditor.publishSuccess");
  });

  it("activates the chosen published version and shows the resulting active version", async () => {
    renderPage();
    await screen.findByTestId("flow");
    fireEvent.click(screen.getByRole("button", { name: /activate/i }));

    const dialog = await screen.findByRole("dialog");
    const select = within(dialog).getByLabelText(/published version/i);
    expect(select).toHaveValue("wf-1:3");
    fireEvent.click(within(dialog).getByRole("button", { name: "Confirm" }));

    await waitFor(() => expect(callsTo(activatePath)).toHaveLength(1));
    expect(post).toHaveBeenCalledWith(activatePath, {
      params: { path: { workflow_id: "wf-1" } },
      body: { version_id: "wf-1:3", expected_active_revision: 3, confirm_stale_base: false },
    });
    const notice = await screen.findByTestId("editor-notice");
    expect(notice).toHaveAttribute("data-key", "workflowEditor.activateSuccess");
    expect(notice).toHaveAttribute("data-version", "3");
    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
    // The workflow state is refreshed after the activation so the UI never
    // shows a stale active version.
    const workflowLoads = get.mock.calls.filter(([path]) => path === workflowPath);
    expect(workflowLoads.length).toBeGreaterThanOrEqual(2);
    const activateOrder = post.mock.invocationCallOrder.find((_order, index) => post.mock.calls[index]?.[0] === activatePath);
    expect(workflowLoads.length).toBeGreaterThan(0);
    expect(activateOrder).toBeLessThan(get.mock.invocationCallOrder[get.mock.invocationCallOrder.length - 1]);
  });

  it("adopts the returned active revision and retries after an activation conflict", async () => {
    post.mockImplementationOnce(() => Promise.resolve(kosmoConflict("errors.workflow.active_revision_conflict", { current_revision: 4 })));
    post.mockImplementationOnce(() => Promise.resolve({ data: { version_id: "wf-1:3", active_revision: 4 } }));
    renderPage();
    await screen.findByTestId("flow");
    fireEvent.click(screen.getByRole("button", { name: /activate/i }));
    const dialog = await screen.findByRole("dialog");
    fireEvent.click(within(dialog).getByRole("button", { name: "Confirm" }));

    await waitFor(() => expect(callsTo(activatePath)).toHaveLength(2));
    expect(callsTo(activatePath)[1]?.[1]?.body).toEqual({ version_id: "wf-1:3", expected_active_revision: 4, confirm_stale_base: false });
    expect(await screen.findByTestId("editor-notice")).toHaveAttribute("data-version", "4");
    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
  });

  it("requires explicit confirmation before activating a stale base", async () => {
    post.mockImplementationOnce(() => Promise.resolve(kosmoConflict("errors.workflow.stale_base_confirmation_required", { active_version_id: "wf-1:3" })));
    post.mockImplementationOnce(() => Promise.resolve({ data: { version_id: "wf-1:3", active_revision: 3 } }));
    renderPage();
    await screen.findByTestId("flow");
    fireEvent.click(screen.getByRole("button", { name: /activate/i }));
    const activateDialog = await screen.findByRole("dialog");
    fireEvent.click(within(activateDialog).getByRole("button", { name: "Confirm" }));

    const confirmDialog = await screen.findByRole("alertdialog");
    fireEvent.click(within(confirmDialog).getByRole("button", { name: /anyway/i }));

    await waitFor(() => expect(callsTo(activatePath)).toHaveLength(2));
    expect(callsTo(activatePath)[1]?.[1]?.body).toEqual({ version_id: "wf-1:3", expected_active_revision: 3, confirm_stale_base: true });
    expect(await screen.findByTestId("editor-notice")).toHaveAttribute("data-key", "workflowEditor.activateSuccess");
  });

  it("maps server draft-validation issues to the affected node and keeps unlocatable ones in the summary", async () => {
    put.mockResolvedValue({ data: { revision: 2, issues: [
      { message_key: "errors.workflow.workflow_not_found", params: { node_id: "start", workflow_id: "absent" } },
      { message_key: "errors.workflow.cycle", params: {} },
    ] } });
    renderPage();
    await screen.findByTestId("flow");
    fireEvent.click(screen.getByRole("button", { name: "Save draft" }));
    await waitFor(() => expect(put).toHaveBeenCalledTimes(1));

    // The located issue surfaces on the affected node's properties panel…
    fireEvent.click(screen.getByRole("button", { name: "select start" }));
    const panel = screen.getByRole("complementary", { name: catalogText("editor.properties") });
    const locatedText = catalogText("errors.workflow.workflow_not_found", { node_id: "start", workflow_id: "absent" });
    expect(within(panel).getByText(locatedText)).toBeInTheDocument();
    // …exactly once: it does not leak into the global summary…
    expect(screen.getAllByText(locatedText)).toHaveLength(1);
    // …and the unlocatable issue stays in the summary instead of a node.
    expect(screen.getByText(catalogText("errors.workflow.cycle"))).toBeInTheDocument();
    expect(within(panel).queryByText(catalogText("errors.workflow.cycle"))).not.toBeInTheDocument();
  });

  it("keeps the Save-draft label with aria-busy while the save is in flight", async () => {
    let resolveSave: (value: unknown) => void = () => {};
    put.mockImplementationOnce(() => new Promise((resolve) => { resolveSave = resolve; }));
    renderPage();
    await screen.findByTestId("flow");
    fireEvent.click(screen.getByRole("button", { name: "Save draft" }));

    const saveButton = screen.getByRole("button", { name: "Save draft" });
    expect(saveButton).toHaveAttribute("aria-busy", "true");
    expect(saveButton).toBeDisabled();
    // The label stays put; only the shared spinner and aria-busy signal flight.
    expect(saveButton).toHaveTextContent("Save draft");
    expect(saveButton).not.toHaveTextContent(catalogText("workflowEditor.saving"));

    resolveSave({ data: { revision: 2, issues: [] } });
    await waitFor(() => expect(saveButton).not.toBeDisabled());
  });
});

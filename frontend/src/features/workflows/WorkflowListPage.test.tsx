import { beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes, useLocation } from "react-router";
import i18next from "i18next";

import { ICON_NAMES } from "@/components/ui/icon-names";

const { get, post } = vi.hoisted(() => ({ get: vi.fn(), post: vi.fn() }));
vi.mock("@/api/auth", () => ({ api: { GET: get, POST: post } }));

import { WorkflowListPage } from "./WorkflowListPage";

/** Resolves through i18next so assertions hold both before and after the pending catalog keys land. */
const catalogText = (key: string) => String(i18next.t(key as never));

// jsdom does not implement ResizeObserver, which the Radix popper-based
// tooltip content measures with (same no-op stub convention as
// RowActions.test.tsx / tooltip.test.tsx).
class ResizeObserverStub {
  observe() {}
  unobserve() {}
  disconnect() {}
}
vi.stubGlobal("ResizeObserver", ResizeObserverStub);

/**
 * Exact backend contracts (backend/app/api/routes/workflows.py, backed by
 * backend/tests/domain/test_workflow_drafts.py):
 * - POST /workflows → 201 WorkflowVersionResponse {id, workflow_id, version, definition}
 * - POST /workflows/{workflow_id}/drafts → 201 {draft_id, revision}
 * - Error bodies are flat {code, message_key, params?, details?} (backend/app/api/errors.py).
 */
const createdWorkflow = {
  id: "ver-1",
  workflow_id: "wf-new",
  version: 1,
  definition: {
    schema_version: "v1",
    name: "Untitled workflow",
    nodes: [
      { type: "start", id: "start", input_form: [{ name: "topic", type: "string", required: true, label_message_key: "workflow.topic.label" }] },
      { type: "end", id: "end" },
    ],
    edges: [{ from: "start", to: "end" }],
  },
};
const createdDraft = { draft_id: "draft-1", revision: 1 };

function LocationProbe() {
  const location = useLocation();
  return <div data-testid="location">{location.pathname}{location.search}</div>;
}

function renderPage() {
  return render(<MemoryRouter initialEntries={["/workflows"]}><Routes>
    <Route path="/workflows" element={<WorkflowListPage />} />
    <Route path="/workflows/:id/edit" element={<LocationProbe />} />
    {/* Catch-all probe so navigation assertions cover routes outside this file. */}
    <Route path="*" element={<LocationProbe />} />
  </Routes></MemoryRouter>);
}

function deferred() {
  let resolve!: (value: { data: unknown }) => void;
  const promise = new Promise<{ data: unknown }>((res) => { resolve = res; });
  return { promise, resolve };
}

describe("workflow list", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    get.mockResolvedValue({ data: [] });
    post.mockResolvedValue({ data: createdWorkflow });
  });

  it("renders workflow metadata and active/publish status", async () => {
    get.mockResolvedValue({ data: [
      { id: "wf-live", name: "Release review", active_version: { id: "v1", version: 3, definition: {} } },
      { id: "wf-draft", name: "Unpublished flow", active_version: null },
    ] });
    renderPage();

    const live = await screen.findByRole("listitem", { name: /Release review/ });
    expect(within(live).getByText("Version 3")).toBeInTheDocument();
    expect(within(live).getByText("Published")).toBeInTheDocument();
    expect(within(live).getByText("Date unavailable")).toBeInTheDocument();
    const draft = screen.getByRole("listitem", { name: /Unpublished flow/ });
    expect(within(draft).getByText("No active version")).toBeInTheDocument();
    expect(within(draft).getByText("Publication status unavailable")).toBeInTheDocument();
  });

  it("offers the generic Add action and the descriptive first-run CTA with a leading add icon", async () => {
    renderPage();
    expect(await screen.findByText("No workflows yet")).toBeInTheDocument();

    const add = screen.getByRole("button", { name: "Add" });
    expect(within(add).getByText(ICON_NAMES.add)).toHaveAttribute("aria-hidden", "true");

    const createFirst = screen.getByRole("button", { name: "Create your first workflow" });
    expect(within(createFirst).getByText(ICON_NAMES.add)).toHaveAttribute("aria-hidden", "true");
  });

  it("renders each row's Edit action as a trailing icon link inside the shared actions group", async () => {
    get.mockResolvedValue({ data: [{ id: "wf-1", name: "Review", active_version: null }] });
    renderPage();
    const row = await screen.findByRole("listitem", { name: /Review/ });
    const actions = within(row).getByRole("group");
    const edit = within(actions).getByRole("link", { name: "Edit" });
    expect(within(edit).getByText(ICON_NAMES.edit)).toHaveAttribute("aria-hidden", "true");
    // Every action stays a link, with no nested button inside (the version-less
    // row's Run action is a disabled link, not a button).
    expect(within(actions).getAllByRole("link")).toHaveLength(2);
    expect(within(actions).queryAllByRole("button")).toHaveLength(0);

    await userEvent.click(edit);
    expect(screen.getByTestId("location")).toHaveTextContent("/workflows/wf-1/edit");
  });

  it("links the row Run action to the new-task page with the workflow preselected", async () => {
    get.mockResolvedValue({ data: [{ id: "wf-1", name: "Review", active_version: { id: "v1", version: 2, definition: {} } }] });
    renderPage();
    const row = await screen.findByRole("listitem", { name: /Review/ });
    const run = within(row).getByRole("link", { name: catalogText("workflows.list.run") });
    expect(within(run).getByText(ICON_NAMES.run)).toHaveAttribute("aria-hidden", "true");

    await userEvent.click(run);
    expect(screen.getByTestId("location")).toHaveTextContent("/tasks/new?workflowId=wf-1");
  });

  it("disables the row Run action with a reason when the workflow has no active version", async () => {
    get.mockResolvedValue({ data: [{ id: "wf-draft", name: "Unpublished flow", active_version: null }] });
    renderPage();
    const row = await screen.findByRole("listitem", { name: /Unpublished flow/ });
    const run = within(row).getByRole("link", { name: catalogText("workflows.list.run") });
    expect(run).toHaveAttribute("aria-disabled", "true");

    await userEvent.click(run);
    // No navigation happened: the workflow list is still on screen.
    expect(screen.getByRole("listitem", { name: /Unpublished flow/ })).toBeInTheDocument();

    await userEvent.hover(run);
    expect(await screen.findByRole("tooltip")).toHaveTextContent(catalogText("workflows.list.runUnavailable"));
  });

  it("supplements the row Edit action with a tooltip without replacing its accessible name", async () => {
    get.mockResolvedValue({ data: [{ id: "wf-1", name: "Review", active_version: null }] });
    renderPage();
    const row = await screen.findByRole("listitem", { name: /Review/ });
    const edit = within(row).getByRole("link", { name: "Edit" });

    await userEvent.hover(edit);

    const tooltip = await screen.findByRole("tooltip");
    expect(tooltip).toHaveTextContent("Edit");
    expect(edit).toHaveAttribute("aria-describedby", tooltip.id);
    expect(edit).toHaveAccessibleName("Edit");
  });

  it("creates a workflow and a draft from the backend contracts, then navigates to the editor URL", async () => {
    post.mockReset();
    post.mockResolvedValueOnce({ data: createdWorkflow }).mockResolvedValueOnce({ data: createdDraft });
    renderPage();
    await userEvent.click(await screen.findByRole("button", { name: "Add" }));

    expect(post).toHaveBeenNthCalledWith(1, "/workflows", { body: createdWorkflow.definition });
    expect(post).toHaveBeenNthCalledWith(2, "/workflows/{workflow_id}/drafts", { params: { path: { workflow_id: createdWorkflow.workflow_id } } });
    expect(await screen.findByTestId("location")).toHaveTextContent("/workflows/wf-new/edit?draftId=draft-1");
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });

  it("keeps a stable label with busy feedback while creation is in flight and ignores duplicate submits", async () => {
    post.mockReset();
    const pending = deferred();
    post.mockImplementationOnce(() => pending.promise).mockResolvedValueOnce({ data: createdDraft });
    renderPage();
    const create = await screen.findByRole("button", { name: "Create your first workflow" });
    await userEvent.click(create);
    expect(create).toBeDisabled();
    expect(create).toHaveAttribute("aria-busy", "true");
    // The displayed label stays stable while loading; feedback comes from the
    // decorative inline spinner instead of a label swap.
    expect(within(create).getByText("Create your first workflow")).toBeInTheDocument();
    expect(within(create).getByText(ICON_NAMES.spinner)).toHaveAttribute("aria-hidden", "true");

    await userEvent.click(create);
    pending.resolve({ data: createdWorkflow });
    await waitFor(() => expect(post).toHaveBeenCalledTimes(2));
    expect(post).toHaveBeenNthCalledWith(1, "/workflows", expect.anything());
    expect(await screen.findByTestId("location")).toHaveTextContent("/workflows/wf-new/edit");
  });

  it("surfaces backend draft-creation errors without navigating and re-enables creation", async () => {
    post.mockReset();
    post.mockResolvedValueOnce({ data: createdWorkflow })
      .mockResolvedValueOnce({ error: { code: "NOT_FOUND", message_key: "errors.workflow.not_found", params: {}, details: [] } });
    renderPage();
    await userEvent.click(await screen.findByRole("button", { name: "Add" }));

    expect(await screen.findByRole("alert")).toHaveTextContent("Workflow not found.");
    expect(screen.queryByTestId("location")).not.toBeInTheDocument();
    await waitFor(() => expect(screen.getByRole("button", { name: "Add" })).toBeEnabled());
  });

  it("renders flat backend API errors through the Kosmo error alert", async () => {
    get.mockResolvedValue({ error: { code: "PERMISSION_DENIED", message_key: "errors.permission.denied", params: {}, details: [] } });
    renderPage();
    expect(await screen.findByRole("alert")).toHaveTextContent("Permission denied.");
  });
});

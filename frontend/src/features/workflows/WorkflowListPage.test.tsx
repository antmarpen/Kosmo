import { beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes, useLocation } from "react-router";
import i18next from "i18next";

import { ICON_NAMES } from "@/components/ui/icon-names";

const { get, post } = vi.hoisted(() => ({ get: vi.fn(), post: vi.fn() }));
vi.mock("@/api/auth", () => ({ api: { GET: get, POST: post } }));

import { WorkflowListPage } from "./WorkflowListPage";

/** Resolves through i18next so assertions hold both before and after the pending catalog keys land. */
const catalogText = (key: string, params?: Record<string, unknown>) => String(i18next.t(key as never, params as never));

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
 * backend/tests/domain/test_workflow_publication.py):
 * - POST /workflows → 201 WorkflowCreatedResponse {id, name, publication_revision, active_version, draft_id, draft_revision}
 * - Error bodies are flat {code, message_key, params?, details?} (backend/app/api/errors.py).
 */
const createdWorkflow = {
  id: "wf-new",
  name: "Review flow",
  publication_revision: 0,
  active_version: null,
  draft_id: "draft-1",
  draft_revision: 1,
};

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

  it("renders the caller's draft count per row and stays quiet at zero", async () => {
    // Drafts are author-private: the backend already reports only the
    // caller's own drafts per workflow (test_workflow_publication.py).
    get.mockResolvedValue({ data: [
      { id: "wf-1", name: "Reviewed", active_version: null, draft_count: 2 },
      { id: "wf-2", name: "Pristine", active_version: null, draft_count: 0 },
    ] });
    renderPage();

    const row = await screen.findByRole("listitem", { name: /Reviewed/ });
    expect(within(row).getByText(catalogText("workflows.list.draftCount", { count: 2 }))).toBeInTheDocument();
    // Zero drafts show no count badge instead of a meaningless "0 drafts".
    const clean = screen.getByRole("listitem", { name: /Pristine/ });
    expect(within(clean).queryByText(catalogText("workflows.list.draftCount", { count: 0 }))).not.toBeInTheDocument();
  });

  it("offers the generic Add action and the descriptive first-run CTA, both opening the creation dialog", async () => {
    renderPage();
    expect(await screen.findByText("No workflows yet")).toBeInTheDocument();

    await userEvent.click(screen.getByRole("button", { name: "Add" }));
    expect(await screen.findByRole("dialog")).toBeInTheDocument();

    await userEvent.click(screen.getByRole("button", { name: "Cancel" }));
    await userEvent.click(screen.getByRole("button", { name: "Create your first workflow" }));
    expect(await screen.findByRole("dialog")).toBeInTheDocument();
    expect(post).not.toHaveBeenCalled();
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

  it("asks for a name, creates only a workflow with an initial draft, and lands in the editor", async () => {
    post.mockReset();
    post.mockResolvedValueOnce({ data: createdWorkflow });
    renderPage();
    await userEvent.click(await screen.findByRole("button", { name: "Add" }));

    const dialog = await screen.findByRole("dialog");
    await userEvent.type(within(dialog).getByLabelText(catalogText("workflows.new.nameLabel")), "Review flow");
    await userEvent.click(within(dialog).getByRole("button", { name: catalogText("workflows.new.action") }));

    // Creation sends the entered name only; the initial draft comes back in
    // the same response and no version is published.
    expect(post).toHaveBeenCalledTimes(1);
    expect(post).toHaveBeenCalledWith("/workflows", { body: { name: "Review flow" } });
    expect(await screen.findByTestId("location")).toHaveTextContent("/workflows/wf-new/edit?draftId=draft-1");
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });

  it("keeps the dialog open with the entered name and surfaces a duplicate-name conflict", async () => {
    post.mockReset();
    post.mockResolvedValueOnce({ error: { code: "CONFLICT", message_key: "errors.workflow.name_conflict", params: { name: "Review flow" }, details: [] } });
    renderPage();
    await userEvent.click(await screen.findByRole("button", { name: "Add" }));

    const dialog = await screen.findByRole("dialog");
    await userEvent.type(within(dialog).getByLabelText(catalogText("workflows.new.nameLabel")), "Review flow");
    await userEvent.click(within(dialog).getByRole("button", { name: catalogText("workflows.new.action") }));

    expect(await screen.findByRole("alert")).toHaveTextContent("A workflow with this name already exists.");
    expect(within(dialog).getByLabelText(catalogText("workflows.new.nameLabel"))).toHaveValue("Review flow");
    expect(screen.queryByTestId("location")).not.toBeInTheDocument();
    expect(post).toHaveBeenCalledTimes(1);
  });

  it("keeps a stable submit label with busy feedback, holds the dialog open, and ignores duplicate submits", async () => {
    post.mockReset();
    const pending = deferred();
    post.mockImplementationOnce(() => pending.promise);
    renderPage();
    await userEvent.click(await screen.findByRole("button", { name: "Add" }));

    const dialog = await screen.findByRole("dialog");
    await userEvent.type(within(dialog).getByLabelText(catalogText("workflows.new.nameLabel")), "Review flow");
    const submit = within(dialog).getByRole("button", { name: catalogText("workflows.new.action") });
    await userEvent.click(submit);
    expect(submit).toBeDisabled();
    expect(submit).toHaveAttribute("aria-busy", "true");
    // The displayed label stays stable while loading; feedback comes from the
    // decorative inline spinner instead of a label swap.
    expect(within(submit).getByText(catalogText("workflows.new.action"))).toBeInTheDocument();
    expect(within(submit).getByText(ICON_NAMES.spinner)).toHaveAttribute("aria-hidden", "true");
    // Escape cannot dismiss the dialog while the creation is in flight.
    await userEvent.keyboard("{Escape}");
    expect(screen.getByRole("dialog")).toBeInTheDocument();
    await userEvent.click(submit);
    expect(post).toHaveBeenCalledTimes(1);

    pending.resolve({ data: createdWorkflow });
    expect(await screen.findByTestId("location")).toHaveTextContent("/workflows/wf-new/edit?draftId=draft-1");
  });

  it("surfaces backend creation errors without navigating and re-enables creation", async () => {
    post.mockReset();
    post.mockResolvedValueOnce({ error: { code: "PERMISSION_DENIED", message_key: "errors.permission.denied", params: {}, details: [] } });
    renderPage();
    await userEvent.click(await screen.findByRole("button", { name: "Add" }));

    const dialog = await screen.findByRole("dialog");
    await userEvent.type(within(dialog).getByLabelText(catalogText("workflows.new.nameLabel")), "Review flow");
    await userEvent.click(within(dialog).getByRole("button", { name: catalogText("workflows.new.action") }));

    // Creation is a single call; a backend failure keeps the dialog open with
    // the entered name and re-enables the submit for a corrected attempt.
    expect(await screen.findByRole("alert")).toHaveTextContent("Permission denied.");
    expect(screen.queryByTestId("location")).not.toBeInTheDocument();
    expect(within(screen.getByRole("dialog")).getByRole("button", { name: catalogText("workflows.new.action") })).toBeEnabled();
  });

  it("renders flat backend API errors through the Kosmo error alert", async () => {
    get.mockResolvedValue({ error: { code: "PERMISSION_DENIED", message_key: "errors.permission.denied", params: {}, details: [] } });
    renderPage();
    expect(await screen.findByRole("alert")).toHaveTextContent("Permission denied.");
  });
});

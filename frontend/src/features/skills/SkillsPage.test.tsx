import { beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router";

// jsdom does not implement ResizeObserver, which the Radix popper-based
// content under the row actions' tooltips requires.
class ResizeObserverStub {
  observe() {}
  unobserve() {}
  disconnect() {}
}
vi.stubGlobal("ResizeObserver", ResizeObserverStub);

const { get, post, put, del, patch } = vi.hoisted(() => ({
  get: vi.fn(),
  post: vi.fn(),
  put: vi.fn(),
  del: vi.fn(),
  patch: vi.fn(),
}));
vi.mock("@/api/auth", () => ({
  api: { GET: get, POST: post, PUT: put, DELETE: del, PATCH: patch },
}));

let mockCurrentUser: unknown;
vi.mock("@/features/auth/useCurrentUser", () => ({
  useCurrentUser: () => mockCurrentUser,
}));

import { SkillsPage } from "./SkillsPage";

const regularUser = {
  user: { id: "u-1", username: "alex", role: "user" },
  capabilities: {
    scopes: { personal: true, groups: ["team-1"], global: false },
    groups: [{ id: "team-1", name: "Platform", role: "manager" }],
  },
};
const plainUser = {
  user: { id: "u-2", username: "sam", role: "user" },
  capabilities: { scopes: { personal: true, groups: [], global: false }, groups: [] },
};
const adminUser = {
  user: { id: "admin-1", username: "root", role: "admin" },
  capabilities: { scopes: { personal: true, groups: [], global: true }, groups: [] },
};

const ownSkill = {
  id: "s-1",
  name: "Security review",
  owner_user_id: "u-1",
  visibility: "personal",
  group_id: null,
  description: "Checks reports for security issues.",
  instructions: "# Steps\n\nRead the report.",
  updated_at: null,
};
const sharedSkill = {
  id: "s-2",
  name: "Style guide",
  owner_user_id: "someone-else",
  visibility: "global",
  group_id: null,
  description: "Writing rules for report authors.",
  instructions: "Be concise.",
  updated_at: null,
};

/** Mutable server state behind the mocked catalog endpoints. */
let listRows: unknown[] = [];
let detailResponse: unknown;
function mockCatalogApi() {
  // openapi-fetch receives the path pattern as its first argument and
  // resolves it internally, so the mock routes on the pattern.
  get.mockImplementation(async (url: string) => {
    if (url === "/skills") return { data: listRows };
    if (url === "/skills/{skill_id}") {
      return (
        detailResponse ?? { error: { code: "NOT_FOUND", message_key: "errors.skill.not_found" } }
      );
    }
    return { error: { code: "NOT_FOUND", message_key: "errors.skill.not_found" } };
  });
  post.mockResolvedValue({ data: {} });
  patch.mockResolvedValue({ data: {} });
  del.mockResolvedValue({ data: undefined });
}

const renderPage = () =>
  render(
    <MemoryRouter>
      <SkillsPage />
    </MemoryRouter>,
  );

/** Opens the create form and fills it with a complete personal skill. */
async function fillCreateForm({ name = "Doc review", description = "Review drafts.", instructions = "Check the claims." } = {}) {
  await userEvent.click(await screen.findByRole("button", { name: "Add" }));
  await userEvent.type(await screen.findByLabelText("Name"), name);
  await userEvent.type(screen.getByLabelText("Description"), description);
  await userEvent.type(screen.getByLabelText("Instructions"), instructions);
  return { name, description, instructions };
}

describe("skills list", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockCurrentUser = regularUser;
    listRows = [ownSkill];
    detailResponse = undefined;
    mockCatalogApi();
  });

  it("renders the visible entries with name, owner, description and scope", async () => {
    renderPage();
    expect(await screen.findByRole("heading", { level: 1, name: "Skills" })).toBeInTheDocument();
    const entry = await screen.findByRole("listitem");
    expect(within(entry).getByText("Security review")).toBeInTheDocument();
    expect(within(entry).getByText("Owner: u-1")).toBeInTheDocument();
    expect(within(entry).getByText("Checks reports for security issues.")).toBeInTheDocument();
    expect(within(entry).getByText("Personal")).toBeInTheDocument();
  });

  it("offers edit and delete only on entries the user may manage", async () => {
    listRows = [ownSkill, sharedSkill];
    renderPage();
    const items = await screen.findAllByRole("listitem");
    // Own entry: full actions. A visible entry owned by someone else carries
    // no actions — viewing it is not permission to edit it.
    expect(within(items[0]).getByRole("button", { name: "Edit" })).toBeInTheDocument();
    expect(within(items[0]).getByRole("button", { name: "Delete" })).toBeInTheDocument();
    expect(within(items[1]).queryByRole("button", { name: "Edit" })).not.toBeInTheDocument();
    expect(within(items[1]).queryByRole("button", { name: "Delete" })).not.toBeInTheDocument();
  });

  it("offers actions to an administrator on any visible entry", async () => {
    mockCurrentUser = adminUser;
    listRows = [sharedSkill];
    renderPage();
    const entry = await screen.findByRole("listitem");
    expect(within(entry).getByRole("button", { name: "Edit" })).toBeInTheDocument();
    expect(within(entry).getByRole("button", { name: "Delete" })).toBeInTheDocument();
  });
});

describe("skill creation", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockCurrentUser = regularUser;
    listRows = [];
    detailResponse = undefined;
    mockCatalogApi();
  });

  it("submits a personal skill and shows it after the refresh", async () => {
    renderPage();
    const values = await fillCreateForm();
    // The server state changes underneath before the save resolves.
    listRows = [{ ...ownSkill, id: "s-9", name: values.name }];
    await userEvent.click(screen.getByRole("button", { name: "Save skill" }));
    await waitFor(() => expect(post).toHaveBeenCalledTimes(1));
    expect(post).toHaveBeenCalledWith("/skills", {
      body: {
        name: values.name,
        visibility: "personal",
        group_id: null,
        description: values.description,
        instructions: values.instructions,
      },
    });
    // The list refetches after the create and renders the new entry.
    await waitFor(() => expect(get).toHaveBeenCalledTimes(2));
    expect(await screen.findByRole("listitem")).toHaveTextContent(values.name);
  });

  it("keeps every input and shows the keyed error when create fails", async () => {
    post.mockResolvedValue({
      error: { code: "CONFLICT", message_key: "errors.skill.name_duplicate", params: {}, details: [] },
    });
    renderPage();
    const values = await fillCreateForm();
    await userEvent.click(screen.getByRole("button", { name: "Save skill" }));
    expect(await screen.findByRole("alert")).toHaveTextContent(
      "You already have a skill with this name in this scope.",
    );
    // The form stays open with everything the user typed.
    expect(screen.getByLabelText("Name")).toHaveValue(values.name);
    expect(screen.getByLabelText("Description")).toHaveValue(values.description);
    expect(screen.getByLabelText("Instructions")).toHaveValue(values.instructions);
  });

  it("blocks submit while the group scope has no group chosen", async () => {
    renderPage();
    await fillCreateForm();
    await userEvent.click(screen.getByRole("radio", { name: "A managed group" }));
    await userEvent.click(screen.getByRole("button", { name: "Save skill" }));
    expect(await screen.findByRole("alert")).toHaveTextContent(
      "The visibility and group combination is invalid.",
    );
    expect(post).not.toHaveBeenCalled();
  });

  it("renders a safe preview of the instructions and returns to the editor with the text intact", async () => {
    renderPage();
    await fillCreateForm({ instructions: "# Steps\n\nRead the report." });
    await userEvent.click(screen.getByRole("button", { name: "Preview" }));
    expect(screen.getByRole("heading", { name: "Steps" })).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Write" }));
    expect(screen.getByLabelText("Instructions")).toHaveValue("# Steps\n\nRead the report.");
  });
});

describe("skill editing", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockCurrentUser = regularUser;
    listRows = [ownSkill];
    detailResponse = undefined;
    mockCatalogApi();
  });

  it("loads the detail, prefills the form and submits the changes", async () => {
    detailResponse = { data: ownSkill };
    renderPage();
    const entry = await screen.findByRole("listitem");
    await userEvent.click(within(entry).getByRole("button", { name: "Edit" }));
    // The form hydrates from the detail endpoint, not the stale list row.
    expect(get).toHaveBeenCalledWith("/skills/{skill_id}", { params: { path: { skill_id: "s-1" } } });
    const nameInput = await screen.findByLabelText("Name");
    expect(nameInput).toHaveValue("Security review");
    expect(screen.getByLabelText("Instructions")).toHaveValue("# Steps\n\nRead the report.");
    listRows = [{ ...ownSkill, name: "Security review v2" }];
    await userEvent.clear(nameInput);
    await userEvent.type(nameInput, "Security review v2");
    await userEvent.click(screen.getByRole("button", { name: "Save skill" }));
    await waitFor(() => expect(patch).toHaveBeenCalledTimes(1));
    expect(patch).toHaveBeenCalledWith("/skills/{skill_id}", {
      params: { path: { skill_id: "s-1" } },
      body: {
        name: "Security review v2",
        visibility: "personal",
        group_id: null,
        description: "Checks reports for security issues.",
        instructions: "# Steps\n\nRead the report.",
      },
    });
    // Initial list load + detail hydration + silent refresh after the save.
    await waitFor(() => expect(get).toHaveBeenCalledTimes(3));
    expect(await screen.findByText("Security review v2")).toBeInTheDocument();
  });

  it("surfaces a keyed error and keeps the list when the entry became invisible", async () => {
    detailResponse = {
      error: { code: "FORBIDDEN", message_key: "errors.skill.not_found", params: {}, details: [] },
    };
    renderPage();
    const entry = await screen.findByRole("listitem");
    await userEvent.click(within(entry).getByRole("button", { name: "Edit" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Skill not found.");
    // No form renders from an entry the user cannot load…
    expect(screen.queryByLabelText("Name")).not.toBeInTheDocument();
    // …and "Back to skills" returns to the usable list.
    await userEvent.click(screen.getByRole("button", { name: "Back to skills" }));
    expect(await screen.findByRole("listitem")).toHaveTextContent("Security review");
  });
});

describe("skill deletion", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockCurrentUser = regularUser;
    listRows = [ownSkill];
    detailResponse = undefined;
    mockCatalogApi();
  });

  it("deletes after the styled confirmation and refreshes the list", async () => {
    listRows = [ownSkill];
    renderPage();
    await userEvent.click(await screen.findByRole("button", { name: "Delete" }));
    const dialog = await screen.findByRole("alertdialog");
    expect(within(dialog).getByText("Delete skill")).toBeInTheDocument();
    expect(within(dialog).getByText(/Security review/)).toBeInTheDocument();
    // The server state changes underneath before the confirmation resolves.
    listRows = [];
    await userEvent.click(within(dialog).getByRole("button", { name: "Delete" }));
    await waitFor(() =>
      expect(del).toHaveBeenCalledWith("/skills/{skill_id}", { params: { path: { skill_id: "s-1" } } }),
    );
    await waitFor(() => expect(get).toHaveBeenCalledTimes(2));
    await waitFor(() => expect(screen.queryByRole("listitem")).not.toBeInTheDocument());
  });

  it("surfaces a keyed delete failure and keeps the row", async () => {
    del.mockResolvedValue({
      error: { code: "NOT_FOUND", message_key: "errors.skill.not_found", params: {}, details: [] },
    });
    renderPage();
    await userEvent.click(await screen.findByRole("button", { name: "Delete" }));
    await userEvent.click(
      within(await screen.findByRole("alertdialog")).getByRole("button", { name: "Delete" }),
    );
    expect(await screen.findByRole("alert")).toHaveTextContent("Skill not found.");
    expect(screen.getByRole("listitem")).toBeInTheDocument();
  });

  it("lands focus on a surviving row action after the deleted row disappears", async () => {
    // The administrator can act on every visible entry, so both rows carry
    // row actions and either one can be deleted.
    mockCurrentUser = adminUser;
    listRows = [ownSkill, sharedSkill];
    renderPage();
    const items = await screen.findAllByRole("listitem");
    // Delete the second row; the survivor (the user's own entry) keeps its
    // row actions and inherits the list position.
    await userEvent.click(within(items[1]).getByRole("button", { name: "Delete" }));
    listRows = [ownSkill];
    await userEvent.click(within(await screen.findByRole("alertdialog")).getByRole("button", { name: "Delete" }));
    await waitFor(() => expect(screen.getAllByRole("listitem")).toHaveLength(1));
    await waitFor(() => {
      const focus = document.activeElement as HTMLElement | null;
      expect(focus).not.toBe(document.body);
      expect(focus?.closest("li")).toHaveTextContent("Security review");
    });
  });

  it("lands focus on the page Add action when the deleted row was the only one", async () => {
    renderPage();
    await userEvent.click(await screen.findByRole("button", { name: "Delete" }));
    listRows = [];
    await userEvent.click(within(await screen.findByRole("alertdialog")).getByRole("button", { name: "Delete" }));
    await waitFor(() => expect(screen.queryByRole("listitem")).not.toBeInTheDocument());
    await waitFor(() => expect(screen.getByRole("button", { name: "Add" })).toHaveFocus());
  });
});

describe("scope availability", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    listRows = [];
    detailResponse = undefined;
    mockCatalogApi();
  });

  it("offers personal only to a user with no managed groups and no admin rights", async () => {
    mockCurrentUser = plainUser;
    renderPage();
    await userEvent.click(await screen.findByRole("button", { name: "Add" }));
    expect(await screen.findByRole("radio", { name: "Just me" })).toBeInTheDocument();
    expect(screen.queryByRole("radio", { name: "A managed group" })).not.toBeInTheDocument();
    expect(screen.queryByRole("radio", { name: "Everyone (global)" })).not.toBeInTheDocument();
  });

  it("offers the group scope only to a user who manages a group", async () => {
    mockCurrentUser = regularUser;
    renderPage();
    await userEvent.click(await screen.findByRole("button", { name: "Add" }));
    expect(await screen.findByRole("radio", { name: "A managed group" })).toBeInTheDocument();
    expect(screen.queryByRole("radio", { name: "Everyone (global)" })).not.toBeInTheDocument();
  });

  it("offers the global scope only to administrators", async () => {
    mockCurrentUser = adminUser;
    renderPage();
    await userEvent.click(await screen.findByRole("button", { name: "Add" }));
    expect(await screen.findByRole("radio", { name: "Everyone (global)" })).toBeInTheDocument();
    expect(screen.queryByRole("radio", { name: "A managed group" })).not.toBeInTheDocument();
  });
});

describe("focus continuity when the form closes", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockCurrentUser = regularUser;
    listRows = [ownSkill];
    detailResponse = undefined;
    mockCatalogApi();
  });

  it("returns focus to the row's edit action after cancelling an edit", async () => {
    detailResponse = { data: ownSkill };
    renderPage();
    const items = await screen.findAllByRole("listitem");
    await userEvent.click(within(items[0]).getByRole("button", { name: "Edit" }));
    await screen.findByLabelText("Name");
    await userEvent.click(screen.getByRole("button", { name: "Cancel" }));
    const refreshed = await screen.findAllByRole("listitem");
    await waitFor(() =>
      expect(within(refreshed[0]).getByRole("button", { name: "Edit" })).toHaveFocus(),
    );
  });

  it("returns focus to the page Add action after cancelling a create", async () => {
    renderPage();
    await userEvent.click(await screen.findByRole("button", { name: "Add" }));
    await screen.findByLabelText("Name");
    await userEvent.click(screen.getByRole("button", { name: "Cancel" }));
    await waitFor(() => expect(screen.getByRole("button", { name: "Add" })).toHaveFocus());
  });
});

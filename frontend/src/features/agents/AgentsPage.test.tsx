import { beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router";

// jsdom does not implement ResizeObserver, which the Radix popper-based
// content under the searchable selects and row actions requires.
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

import { AgentsPage } from "./AgentsPage";

const regularUser = {
  user: { id: "u-1", username: "alex", role: "user" },
  capabilities: {
    scopes: { personal: true, groups: ["team-1"], global: false },
    groups: [{ id: "team-1", name: "Platform", role: "manager" }],
  },
};
const adminUser = {
  user: { id: "admin-1", username: "root", role: "admin" },
  capabilities: { scopes: { personal: true, groups: [], global: true }, groups: [] },
};

const ownAgent = {
  id: "a-1",
  name: "Report agent",
  owner_user_id: "u-1",
  visibility: "personal",
  group_id: null,
  runtime: "opencode",
  model: "default",
  reasoning_effort: null,
  instructions: "# Be terse.",
  mcp_ids: [],
  skill_ids: [],
  updated_at: null,
};
const sharedAgent = {
  ...ownAgent,
  id: "a-2",
  name: "Shared agent",
  owner_user_id: "someone-else",
  visibility: "global",
};
/**
 * An agent saved while references and a model were available that have since
 * disappeared from the actor's view: one MCP id and one skill id no longer
 * resolve, the reasoning effort is not one of the advertised values, and the
 * stored model is not in the discovered list. Editing must surface all three
 * instead of silently normalizing them.
 */
const staleAgent = {
  ...ownAgent,
  id: "a-3",
  name: "Ops agent",
  model: "nan/qwen3.6",
  reasoning_effort: "ultra",
  instructions: "# Ops runbook.",
  mcp_ids: ["m-1", "m-gone"],
  skill_ids: ["s-gone"],
};

const mcpRows = [
  { id: "m-1", name: "Repo search", owner_user_id: "u-1", visibility: "personal", group_id: null, updated_at: null },
  { id: "m-2", name: "Docs fetch", owner_user_id: "someone-else", visibility: "global", group_id: null, updated_at: null },
  { id: "m-3", name: "Web cache", owner_user_id: "u-1", visibility: "personal", group_id: null, updated_at: null },
];
const skillRows = [
  {
    id: "s-1",
    name: "Security review",
    owner_user_id: "u-1",
    visibility: "personal",
    group_id: null,
    description: "Checks reports for security issues.",
    instructions: "Check the claims.",
    updated_at: null,
  },
];

/** Mutable server state behind the mocked catalog and discovery endpoints. */
let listRows: unknown[] = [];
let detailResponse: unknown;
let modelDiscovery: unknown;
function mockCatalogApi() {
  // openapi-fetch receives the path pattern as its first argument and
  // resolves it internally, so the mock routes on the pattern.
  get.mockImplementation(async (url: string) => {
    if (url === "/agents") return { data: listRows };
    if (url === "/agents/{agent_id}") {
      return (
        detailResponse ?? { error: { code: "NOT_FOUND", message_key: "errors.agent.not_found" } }
      );
    }
    if (url === "/mcp-servers") return { data: mcpRows };
    if (url === "/skills") return { data: skillRows };
    return { error: { code: "NOT_FOUND", message_key: "errors.agent.not_found" } };
  });
  post.mockImplementation(async (url: string) => {
    if (url === "/providers/opencode/config/verify") {
      return (
        modelDiscovery ?? {
          data: { valid: true, violations: [], models: ["opencode/big-pickle", "nan/glm5.3"] },
        }
      );
    }
    if (url === "/agents") return { data: {} };
    return { error: { code: "NOT_FOUND", message_key: "errors.agent.not_found" } };
  });
  patch.mockResolvedValue({ data: {} });
  del.mockResolvedValue({ data: undefined });
}

const renderPage = () =>
  render(
    <MemoryRouter>
      <AgentsPage />
    </MemoryRouter>,
  );

/** Opens the create form and fills the name. */
async function openCreateForm(name = "Report agent") {
  await userEvent.click(await screen.findByRole("button", { name: "Add" }));
  await userEvent.type(await screen.findByLabelText("Name"), name);
}

/** Number of list requests the page made (the form's parallel reference loads excluded). */
function agentListCalls() {
  return get.mock.calls.filter(([url]) => url === "/agents").length;
}

/** Chip names in authored order, read from each chip's name span (the icon ligature excluded). */
function chipNames(chips: HTMLElement) {
  return Array.from(chips.querySelectorAll("li > span")).map((span) => span.textContent);
}

/** Chooses an option in a searchable combobox (clears the query first). */
async function chooseOption(ariaLabel: string, optionName: string) {
  const input = screen.getByRole("combobox", { name: ariaLabel });
  await userEvent.click(input);
  await userEvent.clear(input);
  // Options may carry a secondary description line, so the accessible name
  // continues past the option name ("Security review Checks reports…").
  // ByRole string names match the full name, so anchor a regex instead.
  const escaped = optionName.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
  await userEvent.click(await screen.findByRole("option", { name: new RegExp(`^${escaped}`) }));
}

describe("agents list", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockCurrentUser = regularUser;
    listRows = [ownAgent];
    detailResponse = undefined;
    modelDiscovery = undefined;
    mockCatalogApi();
  });

  it("renders the visible entries with name, owner, model and scope", async () => {
    renderPage();
    expect(await screen.findByRole("heading", { level: 1, name: "Agents" })).toBeInTheDocument();
    const entry = await screen.findByRole("listitem");
    expect(within(entry).getByText("Report agent")).toBeInTheDocument();
    expect(within(entry).getByText("Owner: u-1")).toBeInTheDocument();
    // The explicit `default` model convention reads as the runtime default.
    expect(within(entry).getByText("Runtime default")).toBeInTheDocument();
    expect(within(entry).getByText("Personal")).toBeInTheDocument();
  });

  it("offers edit and delete only on entries the user may manage", async () => {
    listRows = [ownAgent, sharedAgent];
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
    listRows = [sharedAgent];
    renderPage();
    const entry = await screen.findByRole("listitem");
    expect(within(entry).getByRole("button", { name: "Edit" })).toBeInTheDocument();
    expect(within(entry).getByRole("button", { name: "Delete" })).toBeInTheDocument();
  });
});

describe("agent creation", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockCurrentUser = regularUser;
    listRows = [];
    detailResponse = undefined;
    modelDiscovery = undefined;
    mockCatalogApi();
  });

  it("submits a personal agent with the default model and runtime-default reasoning when untouched", async () => {
    renderPage();
    await openCreateForm();
    // The server state changes underneath before the save resolves.
    listRows = [{ ...ownAgent, id: "a-9" }];
    await userEvent.click(screen.getByRole("button", { name: "Save agent" }));
    await waitFor(() => expect(post).toHaveBeenCalledWith("/agents", {
      body: {
        name: "Report agent",
        visibility: "personal",
        group_id: null,
        runtime: "opencode",
        model: "default",
        reasoning_effort: null,
        instructions: "",
        mcp_ids: [],
        skill_ids: [],
      },
    }));
    // The list refetches after the create and renders the new entry.
    await waitFor(() => expect(agentListCalls()).toBe(2));
    expect(await screen.findByRole("listitem")).toHaveTextContent("Report agent");
  });

  it("submits the chosen model, reasoning effort and ordered references", async () => {
    renderPage();
    await openCreateForm();
    // Model discovery feeds the searchable model field…
    await chooseOption("Model", "nan/glm5.3");
    expect(screen.getByRole("combobox", { name: "Model" })).toHaveValue("nan/glm5.3");
    // …the bounded reasoning select offers the advertised values…
    await userEvent.selectOptions(screen.getByLabelText("Reasoning effort"), "high");
    // …and the references keep the authored order.
    await chooseOption("MCP servers", "Docs fetch");
    await userEvent.click(await screen.findByRole("option", { name: "Repo search" }));
    const chips = screen.getByRole("list", { name: "MCP servers" });
    expect(chipNames(chips)).toEqual(["Docs fetch", "Repo search"]);
    await chooseOption("Skills", "Security review");
    await userEvent.type(screen.getByLabelText("Instructions"), "Summarize the report.");
    await userEvent.click(screen.getByRole("button", { name: "Save agent" }));
    await waitFor(() => expect(post).toHaveBeenCalledWith("/agents", {
      body: {
        name: "Report agent",
        visibility: "personal",
        group_id: null,
        runtime: "opencode",
        model: "nan/glm5.3",
        reasoning_effort: "high",
        instructions: "Summarize the report.",
        mcp_ids: ["m-2", "m-1"],
        skill_ids: ["s-1"],
      },
    }));
  });

  it("keeps the authored order when a middle reference is removed", async () => {
    renderPage();
    await openCreateForm();
    await chooseOption("MCP servers", "Repo search");
    await userEvent.click(await screen.findByRole("option", { name: "Docs fetch" }));
    await userEvent.click(await screen.findByRole("option", { name: "Web cache" }));
    const chips = screen.getByRole("list", { name: "MCP servers" });
    expect(chipNames(chips)).toEqual(["Repo search", "Docs fetch", "Web cache"]);
    // Removing the middle chip keeps the relative order of the survivors.
    await userEvent.click(within(chips).getByRole("button", { name: "Remove Docs fetch" }));
    expect(chipNames(chips)).toEqual(["Repo search", "Web cache"]);
    await userEvent.click(screen.getByRole("button", { name: "Save agent" }));
    await waitFor(() => expect(post).toHaveBeenCalledWith("/agents", {
      body: expect.objectContaining({ mcp_ids: ["m-1", "m-3"] }),
    }));
  });

  it("surfaces model-discovery unavailability without blocking authoring", async () => {
    // No saved personal provider configuration exists (or discovery is down):
    // the keyed provider error shows inline and the form still saves with the
    // explicit `default` model convention.
    modelDiscovery = {
      error: { code: "NOT_FOUND", message_key: "errors.provider.config_not_found", params: {}, details: [] },
    };
    renderPage();
    await openCreateForm();
    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Provider configuration not found.",
    );
    expect(screen.getByRole("combobox", { name: "Model" })).toHaveValue("Runtime default");
    await userEvent.click(screen.getByRole("button", { name: "Save agent" }));
    await waitFor(() => expect(post).toHaveBeenCalledWith("/agents", {
      body: expect.objectContaining({ model: "default" }),
    }));
  });

  it("keeps every input and shows the keyed error when create fails", async () => {
    post.mockImplementation(async (url: string) => {
      if (url === "/providers/opencode/config/verify") {
        return { data: { valid: true, violations: [], models: [] } };
      }
      return {
        error: { code: "CONFLICT", message_key: "errors.agent.name_duplicate", params: {}, details: [] },
      };
    });
    renderPage();
    await openCreateForm();
    await userEvent.type(screen.getByLabelText("Instructions"), "Summarize the report.");
    await userEvent.click(screen.getByRole("button", { name: "Save agent" }));
    expect(await screen.findByRole("alert")).toHaveTextContent(
      "You already have an agent with this name in this scope.",
    );
    // The form stays open with everything the user typed.
    expect(screen.getByLabelText("Name")).toHaveValue("Report agent");
    expect(screen.getByLabelText("Instructions")).toHaveValue("Summarize the report.");
  });
});

describe("agent editing", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockCurrentUser = regularUser;
    listRows = [ownAgent];
    detailResponse = undefined;
    modelDiscovery = undefined;
    mockCatalogApi();
  });

  it("loads the detail, prefills the defaults and submits the changes", async () => {
    detailResponse = { data: ownAgent };
    renderPage();
    const entry = await screen.findByRole("listitem");
    await userEvent.click(within(entry).getByRole("button", { name: "Edit" }));
    // The form hydrates from the detail endpoint, not the stale list row.
    expect(get).toHaveBeenCalledWith("/agents/{agent_id}", { params: { path: { agent_id: "a-1" } } });
    const nameInput = await screen.findByLabelText("Name");
    expect(nameInput).toHaveValue("Report agent");
    expect(screen.getByRole("combobox", { name: "Model" })).toHaveValue("Runtime default");
    expect(screen.getByLabelText<HTMLElement>("Reasoning effort")).toHaveValue("");
    expect(screen.getByLabelText("Instructions")).toHaveValue("# Be terse.");
    await userEvent.clear(nameInput);
    await userEvent.type(nameInput, "Report agent v2");
    listRows = [{ ...ownAgent, name: "Report agent v2" }];
    await userEvent.click(screen.getByRole("button", { name: "Save agent" }));
    await waitFor(() => expect(patch).toHaveBeenCalledWith("/agents/{agent_id}", {
      params: { path: { agent_id: "a-1" } },
      body: {
        name: "Report agent v2",
        visibility: "personal",
        group_id: null,
        model: "default",
        reasoning_effort: null,
        instructions: "# Be terse.",
        mcp_ids: [],
        skill_ids: [],
      },
    }));
    // Initial list load + silent refresh after the save (the form's parallel
    // reference loads are excluded from the count).
    await waitFor(() => expect(agentListCalls()).toBe(2));
    expect(await screen.findByText("Report agent v2")).toBeInTheDocument();
  });

  it("shows unavailable references as removable chips and submits their removal", async () => {
    detailResponse = { data: staleAgent };
    renderPage();
    const entry = await screen.findByRole("listitem");
    await userEvent.click(within(entry).getByRole("button", { name: "Edit" }));
    // Stale references render as unavailable chips, never silently dropped…
    expect(await screen.findByText("m-gone · Unavailable")).toBeInTheDocument();
    expect(screen.getByText("s-gone · Unavailable")).toBeInTheDocument();
    expect(screen.getByText("Repo search")).toBeInTheDocument();
    // …and each chip carries its own remove button.
    const chips = screen.getByRole("list", { name: "MCP servers" });
    await userEvent.click(within(chips).getByRole("button", { name: "Remove m-gone · Unavailable" }));
    expect(screen.queryByText("m-gone · Unavailable")).not.toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Save agent" }));
    await waitFor(() => expect(patch).toHaveBeenCalledWith("/agents/{agent_id}", {
      params: { path: { agent_id: "a-3" } },
      body: expect.objectContaining({ mcp_ids: ["m-1"], skill_ids: ["s-gone"] }),
    }));
  });

  it("preserves unrelated stored fields when a central edit only changes the name", async () => {
    detailResponse = { data: staleAgent };
    renderPage();
    const entry = await screen.findByRole("listitem");
    await userEvent.click(within(entry).getByRole("button", { name: "Edit" }));
    // The stored model is not in the discovered list: it stays visible and
    // selected instead of being normalized.
    expect(await screen.findByRole("combobox", { name: "Model" })).toHaveValue("nan/qwen3.6");
    expect(
      screen.getByText(
        "The stored model is not in the discovered list. It is kept until you choose another model.",
      ),
    ).toBeInTheDocument();
    // The unrecognized reasoning effort is preserved with a clear unsupported
    // indication rather than silently normalized.
    const reasoning = screen.getByLabelText<HTMLElement>("Reasoning effort");
    expect(reasoning).toHaveValue("ultra");
    expect(reasoning).toHaveAttribute("aria-describedby", expect.stringContaining("unsupported"));
    expect(
      screen.getByText(
        /“ultra” is not one of the runtime's advertised reasoning efforts/,
      ),
    ).toBeInTheDocument();
    const nameInput = screen.getByLabelText("Name");
    await userEvent.clear(nameInput);
    await userEvent.type(nameInput, "Ops agent v2");
    await userEvent.click(screen.getByRole("button", { name: "Save agent" }));
    await waitFor(() => expect(patch).toHaveBeenCalledWith("/agents/{agent_id}", {
      params: { path: { agent_id: "a-3" } },
      body: {
        name: "Ops agent v2",
        visibility: "personal",
        group_id: null,
        model: "nan/qwen3.6",
        reasoning_effort: "ultra",
        instructions: "# Ops runbook.",
        mcp_ids: ["m-1", "m-gone"],
        skill_ids: ["s-gone"],
      },
    }));
  });

  it("offers the runtime default and the advertised effort values as distinct choices, and clearing submits null", async () => {
    detailResponse = { data: { ...ownAgent, reasoning_effort: "high" } };
    renderPage();
    const entry = await screen.findByRole("listitem");
    await userEvent.click(within(entry).getByRole("button", { name: "Edit" }));
    const reasoning = await screen.findByLabelText<HTMLElement>("Reasoning effort");
    expect(reasoning).toHaveValue("high");
    const options = within(reasoning).getAllByRole("option").map((option) => option.textContent);
    expect(options).toEqual([
      "Use runtime default",
      "None",
      "Low",
      "Medium",
      "High",
      "Max",
      "Default",
    ]);
    // Choosing the runtime default clears the stored override explicitly.
    await userEvent.selectOptions(reasoning, "");
    await userEvent.click(screen.getByRole("button", { name: "Save agent" }));
    await waitFor(() => expect(patch).toHaveBeenCalledWith("/agents/{agent_id}", {
      params: { path: { agent_id: "a-1" } },
      body: expect.objectContaining({ reasoning_effort: null }),
    }));
  });

  it("surfaces a keyed error and keeps the list when the agent became invisible", async () => {
    detailResponse = {
      error: { code: "FORBIDDEN", message_key: "errors.agent.not_found", params: {}, details: [] },
    };
    renderPage();
    const entry = await screen.findByRole("listitem");
    await userEvent.click(within(entry).getByRole("button", { name: "Edit" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Agent not found.");
    // No form renders from an entry the user cannot load…
    expect(screen.queryByLabelText("Name")).not.toBeInTheDocument();
    // …and "Back to agents" returns to the usable list.
    await userEvent.click(screen.getByRole("button", { name: "Back to agents" }));
    expect(await screen.findByRole("listitem")).toHaveTextContent("Report agent");
  });
});

describe("agent deletion", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockCurrentUser = regularUser;
    listRows = [ownAgent];
    detailResponse = undefined;
    modelDiscovery = undefined;
    mockCatalogApi();
  });

  it("deletes after the styled confirmation and refreshes the list", async () => {
    renderPage();
    await userEvent.click(await screen.findByRole("button", { name: "Delete" }));
    const dialog = await screen.findByRole("alertdialog");
    expect(within(dialog).getByText("Delete agent")).toBeInTheDocument();
    expect(within(dialog).getByText(/Report agent/)).toBeInTheDocument();
    // The server state changes underneath before the confirmation resolves.
    listRows = [];
    await userEvent.click(within(dialog).getByRole("button", { name: "Delete" }));
    await waitFor(() =>
      expect(del).toHaveBeenCalledWith("/agents/{agent_id}", { params: { path: { agent_id: "a-1" } } }),
    );
    await waitFor(() => expect(agentListCalls()).toBe(2));
    await waitFor(() => expect(screen.queryByRole("listitem")).not.toBeInTheDocument());
  });
});

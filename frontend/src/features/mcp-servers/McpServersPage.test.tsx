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

import { McpServersPage } from "./McpServersPage";

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

const ownMcpList = {
  id: "m-1",
  name: "Repo search",
  owner_user_id: "u-1",
  visibility: "personal",
  group_id: null,
};
const sharedMcpList = {
  id: "m-2",
  name: "Team search",
  owner_user_id: "someone-else",
  visibility: "global",
  group_id: null,
};
const ownMcp = {
  ...ownMcpList,
  transport: {
    type: "stdio",
    command: "npx",
    args: ["-y"],
    env: [
      { name: "API_TOKEN", secret: true, is_set: true },
      { name: "DEBUG", secret: false, is_set: true, value: "1" },
    ],
  },
  updated_at: null,
};

/** Mutable server state behind the mocked catalog endpoints. */
let listRows: unknown[] = [];
let detailResponse: unknown;
function mockCatalogApi() {
  // openapi-fetch receives the path pattern as its first argument and
  // resolves it internally, so the mock routes on the pattern.
  get.mockImplementation(async (url: string) => {
    if (url === "/mcp-servers") return { data: listRows };
    if (url === "/mcp-servers/{server_id}") {
      return (
        detailResponse ?? {
          error: { code: "NOT_FOUND", message_key: "errors.mcp_server.not_found" },
        }
      );
    }
    return { error: { code: "NOT_FOUND", message_key: "errors.mcp_server.not_found" } };
  });
  post.mockResolvedValue({ data: {} });
  patch.mockResolvedValue({ data: {} });
  del.mockResolvedValue({ data: undefined });
}

const renderPage = () =>
  render(
    <MemoryRouter>
      <McpServersPage />
    </MemoryRouter>,
  );

/** Opens the create form and fills a complete personal stdio server with one secret env entry. */
async function fillCreateForm({ name = "Repo search", command = "npx" } = {}) {
  await userEvent.click(await screen.findByRole("button", { name: "Add" }));
  await userEvent.type(await screen.findByLabelText("Name"), name);
  await userEvent.type(screen.getByLabelText("Command"), command);
  await userEvent.type(screen.getByLabelText("Arguments"), "-y\n@acme/server");
  await userEvent.click(screen.getByRole("button", { name: "Add environment variable" }));
  await userEvent.type(screen.getByLabelText("Environment variable name"), "API_TOKEN");
  await userEvent.click(screen.getByRole("switch", { name: "Secret" }));
  await userEvent.type(screen.getByLabelText("Value"), "s3cret");
  return { name, command };
}

describe("mcp servers list", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockCurrentUser = regularUser;
    listRows = [ownMcpList];
    detailResponse = undefined;
    mockCatalogApi();
  });

  it("renders the visible entries with name, owner and scope", async () => {
    renderPage();
    expect(await screen.findByRole("heading", { level: 1, name: "MCP servers" })).toBeInTheDocument();
    const entry = await screen.findByRole("listitem");
    expect(within(entry).getByText("Repo search")).toBeInTheDocument();
    expect(within(entry).getByText("Owner: u-1")).toBeInTheDocument();
    expect(within(entry).getByText("Personal")).toBeInTheDocument();
  });

  it("offers edit and delete only on entries the user may manage", async () => {
    listRows = [ownMcpList, sharedMcpList];
    renderPage();
    const items = await screen.findAllByRole("listitem");
    // A visible entry owned by someone else carries no actions — viewing it
    // is not permission to edit it.
    expect(within(items[0]).getByRole("button", { name: "Edit" })).toBeInTheDocument();
    expect(within(items[0]).getByRole("button", { name: "Delete" })).toBeInTheDocument();
    expect(within(items[1]).queryByRole("button", { name: "Edit" })).not.toBeInTheDocument();
    expect(within(items[1]).queryByRole("button", { name: "Delete" })).not.toBeInTheDocument();
  });

  it("offers actions to an administrator on any visible entry", async () => {
    mockCurrentUser = adminUser;
    listRows = [sharedMcpList];
    renderPage();
    const entry = await screen.findByRole("listitem");
    expect(within(entry).getByRole("button", { name: "Edit" })).toBeInTheDocument();
    expect(within(entry).getByRole("button", { name: "Delete" })).toBeInTheDocument();
  });
});

describe("mcp server creation", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockCurrentUser = regularUser;
    listRows = [];
    detailResponse = undefined;
    mockCatalogApi();
  });

  it("submits the exact create request with a replace secret entry and refetches", async () => {
    renderPage();
    const values = await fillCreateForm();
    // The server state changes underneath before the save resolves.
    listRows = [{ ...ownMcpList, id: "m-9", name: values.name }];
    await userEvent.click(screen.getByRole("button", { name: "Save MCP server" }));
    await waitFor(() => expect(post).toHaveBeenCalledTimes(1));
    expect(post).toHaveBeenCalledWith("/mcp-servers", {
      body: {
        name: values.name,
        visibility: "personal",
        group_id: null,
        transport: {
          type: "stdio",
          command: values.command,
          args: ["-y", "@acme/server"],
          env: [{ name: "API_TOKEN", secret: true, action: "replace", value: "s3cret" }],
        },
      },
    });
    await waitFor(() => expect(get).toHaveBeenCalledTimes(2));
    expect(await screen.findByRole("listitem")).toHaveTextContent(values.name);
  });

  it("keeps every input and shows the keyed error when create fails", async () => {
    post.mockResolvedValue({
      error: {
        code: "CONFLICT",
        message_key: "errors.mcp_server.name_duplicate",
        params: {},
        details: [],
      },
    });
    renderPage();
    await fillCreateForm();
    await userEvent.click(screen.getByRole("button", { name: "Save MCP server" }));
    expect(await screen.findByRole("alert")).toHaveTextContent(
      "You already have an MCP server with this name in this scope.",
    );
    // The form stays open with everything the user typed, including the
    // secret value that never left the client.
    expect(screen.getByLabelText("Name")).toHaveValue("Repo search");
    expect(screen.getByLabelText("Value")).toHaveValue("s3cret");
  });

  it("blocks submit while entries have duplicate names", async () => {
    renderPage();
    await userEvent.click(await screen.findByRole("button", { name: "Add" }));
    await userEvent.type(await screen.findByLabelText("Name"), "Repo search");
    await userEvent.type(screen.getByLabelText("Command"), "npx");
    await userEvent.click(screen.getByRole("button", { name: "Add environment variable" }));
    await userEvent.click(screen.getByRole("button", { name: "Add environment variable" }));
    const nameInputs = screen.getAllByLabelText("Environment variable name");
    await userEvent.type(nameInputs[0], "API_TOKEN");
    await userEvent.type(nameInputs[1], "API_TOKEN");
    await userEvent.type(screen.getAllByLabelText("Value")[0], "a");
    await userEvent.type(screen.getAllByLabelText("Value")[1], "b");
    await userEvent.click(screen.getByRole("button", { name: "Save MCP server" }));
    const alerts = await screen.findAllByRole("alert");
    const messages = alerts.map((alert) => alert.textContent).join(" ");
    expect(messages).toContain("Entry names must be unique.");
    expect(post).not.toHaveBeenCalled();
  });
});

describe("mcp server editing and secret retention", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockCurrentUser = regularUser;
    listRows = [ownMcpList];
    detailResponse = undefined;
    mockCatalogApi();
  });

  it("never preloads the stored secret: the masked input stays empty with a presence marker", async () => {
    detailResponse = { data: ownMcp };
    renderPage();
    const entry = await screen.findByRole("listitem");
    await userEvent.click(within(entry).getByRole("button", { name: "Edit" }));
    expect(get).toHaveBeenCalledWith("/mcp-servers/{server_id}", {
      params: { path: { server_id: "m-1" } },
    });
    const nameInputs = await screen.findAllByLabelText("Environment variable name");
    // A stored secret is never preloaded: the masked input starts empty.
    const secretRow = nameInputs[0].closest("li") as HTMLElement;
    const valueInput = within(secretRow).getByLabelText("Value");
    expect(valueInput).toHaveAttribute("type", "password");
    expect(valueInput).toHaveValue("");
    expect(within(secretRow).getByText("Set")).toBeInTheDocument();
    expect(
      within(secretRow).getByText("Leave blank to keep the stored value."),
    ).toBeInTheDocument();
    // The nonsecret entry value is visible and prefilled.
    const plainRow = nameInputs[1].closest("li") as HTMLElement;
    const plainValue = within(plainRow).getByLabelText("Value");
    expect(plainValue).toHaveAttribute("type", "text");
    expect(plainValue).toHaveValue("1");
    expect(screen.getByLabelText("Arguments")).toHaveValue("-y");
  });

  it("sends keep without a value for an untouched stored secret", async () => {
    detailResponse = { data: ownMcp };
    renderPage();
    const entry = await screen.findByRole("listitem");
    await userEvent.click(within(entry).getByRole("button", { name: "Edit" }));
    await screen.findByLabelText("Name");
    await userEvent.click(screen.getByRole("button", { name: "Save MCP server" }));
    await waitFor(() => expect(patch).toHaveBeenCalledTimes(1));
    expect(patch).toHaveBeenCalledWith("/mcp-servers/{server_id}", {
      params: { path: { server_id: "m-1" } },
      body: {
        name: "Repo search",
        visibility: "personal",
        group_id: null,
        transport: {
          type: "stdio",
          command: "npx",
          args: ["-y"],
          env: [
            { name: "API_TOKEN", secret: true, action: "keep" },
            { name: "DEBUG", secret: false, action: "replace", value: "1" },
          ],
        },
      },
    });
    await waitFor(() => expect(get).toHaveBeenCalledTimes(3));
  });

  it("sends replace with the typed value when the stored secret is rotated", async () => {
    detailResponse = { data: ownMcp };
    renderPage();
    const entry = await screen.findByRole("listitem");
    await userEvent.click(within(entry).getByRole("button", { name: "Edit" }));
    const secretRow = (await screen.findAllByLabelText("Environment variable name"))[0].closest(
      "li",
    ) as HTMLElement;
    await userEvent.type(within(secretRow).getByLabelText("Value"), "rotated");
    await userEvent.click(screen.getByRole("button", { name: "Save MCP server" }));
    await waitFor(() => expect(patch).toHaveBeenCalledTimes(1));
    const body = patch.mock.calls[0][1].body as { transport: { env: unknown[] } };
    expect(body.transport.env[0]).toEqual({
      name: "API_TOKEN",
      secret: true,
      action: "replace",
      value: "rotated",
    });
  });

  it("surfaces localized validation when a rename would keep a stored secret", async () => {
    detailResponse = { data: ownMcp };
    renderPage();
    const entry = await screen.findByRole("listitem");
    await userEvent.click(within(entry).getByRole("button", { name: "Edit" }));
    const nameInput = await screen.findByLabelText("Name");
    await userEvent.clear(nameInput);
    await userEvent.type(nameInput, "Renamed search");
    await userEvent.click(screen.getByRole("button", { name: "Save MCP server" }));
    const alerts = await screen.findAllByRole("alert");
    const messages = alerts.map((alert) => alert.textContent).join(" ");
    expect(messages).toContain("Stored secrets cannot be kept after renaming the server.");
    expect(patch).not.toHaveBeenCalled();
  });

  it("surfaces a keyed error and keeps the list when the entry became invisible", async () => {
    detailResponse = {
      error: { code: "FORBIDDEN", message_key: "errors.mcp_server.not_found", params: {}, details: [] },
    };
    renderPage();
    const entry = await screen.findByRole("listitem");
    await userEvent.click(within(entry).getByRole("button", { name: "Edit" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("MCP server not found.");
    // No form renders from an entry the user cannot load…
    expect(screen.queryByLabelText("Name")).not.toBeInTheDocument();
    // …and "Back to MCP servers" returns to the usable list.
    await userEvent.click(screen.getByRole("button", { name: "Back to MCP servers" }));
    expect(await screen.findByRole("listitem")).toHaveTextContent("Repo search");
  });
});

describe("mcp server deletion", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockCurrentUser = regularUser;
    listRows = [ownMcpList];
    detailResponse = undefined;
    mockCatalogApi();
  });

  it("deletes after the styled confirmation and refreshes the list", async () => {
    renderPage();
    await userEvent.click(await screen.findByRole("button", { name: "Delete" }));
    const dialog = await screen.findByRole("alertdialog");
    expect(within(dialog).getByText("Delete MCP server")).toBeInTheDocument();
    expect(within(dialog).getByText(/Repo search/)).toBeInTheDocument();
    // The server state changes underneath before the confirmation resolves.
    listRows = [];
    await userEvent.click(within(dialog).getByRole("button", { name: "Delete" }));
    await waitFor(() =>
      expect(del).toHaveBeenCalledWith("/mcp-servers/{server_id}", {
        params: { path: { server_id: "m-1" } },
      }),
    );
    await waitFor(() => expect(get).toHaveBeenCalledTimes(2));
    await waitFor(() => expect(screen.queryByRole("listitem")).not.toBeInTheDocument());
  });

  it("surfaces a keyed delete failure and keeps the row", async () => {
    del.mockResolvedValue({
      error: { code: "NOT_FOUND", message_key: "errors.mcp_server.not_found", params: {}, details: [] },
    });
    renderPage();
    await userEvent.click(await screen.findByRole("button", { name: "Delete" }));
    await userEvent.click(
      within(await screen.findByRole("alertdialog")).getByRole("button", { name: "Delete" }),
    );
    expect(await screen.findByRole("alert")).toHaveTextContent("MCP server not found.");
    expect(screen.getByRole("listitem")).toBeInTheDocument();
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
    listRows = [ownMcpList];
    detailResponse = undefined;
    mockCatalogApi();
  });

  it("returns focus to the row's edit action after cancelling an edit", async () => {
    detailResponse = { data: ownMcp };
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

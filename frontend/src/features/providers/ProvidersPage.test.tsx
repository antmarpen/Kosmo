import { beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes } from "react-router";
import { ICON_NAMES } from "@/components/ui/icon-names";

// jsdom does not implement ResizeObserver, which the Radix popper-based
// content under the row actions' tooltips requires.
class ResizeObserverStub {
  observe() {}
  unobserve() {}
  disconnect() {}
}
vi.stubGlobal("ResizeObserver", ResizeObserverStub);

const { get, post, put, del, patch } = vi.hoisted(() => ({ get: vi.fn(), post: vi.fn(), put: vi.fn(), del: vi.fn(), patch: vi.fn() }));
vi.mock("@/api/auth", () => ({ api: { GET: get, POST: post, PUT: put, DELETE: del, PATCH: patch } }));
let mockCapabilities: any;
vi.mock("@/features/auth/useCurrentUser", () => ({ useCurrentUser: () => ({ user: { username: "alex" }, capabilities: mockCapabilities, loading: false, error: null }) }));

import { ProvidersPage } from "./ProvidersPage";

const validConfig = JSON.stringify({ providers: { openai: { options: {}, models: { "gpt-4.1": {} } } } });
const dropzoneName = "Drag and drop your configuration file here, or browse to choose it";
function makeFile(content: string, name = "opencode.json", type = "application/json") { return new File([content], name, { type }); }
/** Selects a configuration through the file picker (the only upload path). */
async function chooseConfig(content: string, name = "opencode.json") {
  await userEvent.upload(screen.getByLabelText(dropzoneName), makeFile(content, name));
  await screen.findByText(`Selected file: ${name}`);
}
const renderPage = () => render(<MemoryRouter initialEntries={["/providers"]}><Routes><Route path="/providers" element={<ProvidersPage />} /></Routes></MemoryRouter>);
async function toUploadStep() {
  await screen.findByRole("heading", { name: "Providers" });
  await userEvent.click(screen.getByRole("button", { name: "Add" }));
  expect(screen.getByRole("button", { name: /Claude Code/ })).toBeDisabled();
  expect(screen.getByRole("button", { name: /Codex/ })).toBeDisabled();
  expect(screen.getAllByText("Coming soon")).toHaveLength(2);
  const opencode = screen.getByRole("button", { name: /OpenCode/ });
  await userEvent.click(opencode);
  await userEvent.click(screen.getByRole("button", { name: "Continue" }));
  await screen.findByRole("heading", { name: "Add your configuration" });
}
/** Runs the mandatory connection test on the connection step. */
async function passConnectionTest() {
  await userEvent.click(screen.getByRole("button", { name: "Test connection" }));
  await screen.findByText("Connection verified with openai/gpt-4.1 (420 ms).");
}
/** Types the mandatory friendly name on the data step. */
async function fillName(value = "Personal gateway") {
  await userEvent.type(screen.getByLabelText(/Configuration name/), value);
}
async function toSaveStep() {
  await toUploadStep();
  await chooseConfig(validConfig);
  await fillName();
  await userEvent.click(screen.getByRole("button", { name: "Continue" }));
  await screen.findByRole("heading", { name: "Test the connection" });
  await passConnectionTest();
  await userEvent.click(screen.getByRole("button", { name: "Continue" }));
  await screen.findByRole("heading", { name: "Choose who can use it" });
}

describe("provider configuration", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockCapabilities = { scopes: { personal: true, groups: [], global: false }, groups: [] };
    get.mockResolvedValue({ data: [] });
    post.mockImplementation(async (url: string) => {
      if (url.endsWith("/candidate/validate")) return { data: { valid: true, violations: [] } };
      if (url.endsWith("/candidate/models")) return { data: { valid: true, violations: [], models: ["openai/gpt-4.1"] } };
      // R5 contract: a successful candidate verification returns a usable
      // proof with its remaining validity; the wizard refuses to treat it as
      // verified otherwise.
      if (url.endsWith("/candidate/verify-model")) return { data: { ok: true, latency_ms: 420, verification_id: "ver-1", proof_expires_in_seconds: 120 } };
      return { data: {} };
    });
    put.mockResolvedValue({ data: { id: "new-provider", verification_status: "verified" } });
  });

  it("renders available type cards and advances only with OpenCode", async () => {
    renderPage();
    await screen.findByRole("heading", { name: "Providers" });
    const addButton = screen.getByRole("button", { name: "Add" });
    expect(within(addButton).getByText(ICON_NAMES.add)).toBeInTheDocument();
    await userEvent.click(addButton);
    expect(screen.getByRole("button", { name: /Claude Code/ })).toBeDisabled();
    expect(screen.getByRole("button", { name: /Codex/ })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Continue" })).toBeDisabled();
    await userEvent.click(screen.getByRole("button", { name: /OpenCode/ }));
    await userEvent.click(screen.getByRole("button", { name: "Continue" }));
    expect(await screen.findByLabelText(dropzoneName)).toBeInTheDocument();
  });

  it("renders structured candidate validation violations inline", async () => {
    post.mockImplementation(async (url: string) => url.endsWith("/candidate/validate")
      ? { data: { valid: false, violations: [{ message_key: "errors.provider.providers_missing" }] } }
      : { data: {} });
    renderPage();
    await toUploadStep();
    await chooseConfig(validConfig);
    await fillName();
    await userEvent.click(screen.getByRole("button", { name: "Continue" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Provider configuration must contain a provider.");
    const validateCall = post.mock.calls.find(([url]) => String(url).endsWith("/candidate/validate"));
    expect(validateCall?.[1]).toEqual({ body: { config: JSON.parse(validConfig) } });
  });

  it("does not show scope choices to a regular user", async () => {
    renderPage();
    await toSaveStep();
    expect(await screen.findByText("This configuration will be personal and visible only to you.")).toBeInTheDocument();
    expect(screen.queryByRole("radiogroup")).not.toBeInTheDocument();
    expect(screen.queryByLabelText("Make available to")).not.toBeInTheDocument();
  });

  it("shows only permitted scope controls for managed groups and administrators", async () => {
    mockCapabilities = { scopes: { personal: true, groups: ["team-1"], global: false }, groups: [{ id: "team-1", name: "Platform", role: "manager" }] };
    renderPage();
    await toSaveStep();
    expect(await screen.findByLabelText("A managed group")).toBeInTheDocument();
    expect(screen.queryByLabelText("Everyone (global)")).not.toBeInTheDocument();
  });

  it("offers global scope only when the user capability allows it", async () => {
    mockCapabilities = { scopes: { personal: true, groups: [], global: true }, groups: [] };
    renderPage();
    await toSaveStep();
    expect(await screen.findByLabelText("Everyone (global)")).toBeInTheDocument();
  });

  it("commits the selected config with the upload endpoint after a successful connection test", async () => {
    renderPage();
    await toSaveStep();
    await userEvent.click(screen.getByRole("button", { name: "Save provider" }));
    await waitFor(() => expect(put).toHaveBeenCalledTimes(1));
    expect(put).toHaveBeenCalledWith("/providers/opencode/config", expect.objectContaining({ body: expect.any(FormData) }));
    const submitted = put.mock.calls[0][1].body as FormData;
    expect(submitted.get("visibility")).toBe("personal");
    expect(submitted.get("name")).toBe("Personal gateway");
    expect(submitted.get("verification_id")).toBe("ver-1");
    expect(submitted.get("selected_model")).toBeNull();
    expect((submitted.get("opencode_json") as File).name).toBe("opencode.json");
    expect(await screen.findByRole("heading", { name: "Providers" })).toBeInTheDocument();
  });

  it("renders metadata-only provider entries with the user-entered name", async () => {
    get.mockResolvedValue({ data: [{ id: "p-1", name: "Team gateway", provider_type: "opencode", visibility: "group", verification_status: "unknown", owner_user_id: "alex", auth_present: false, format: "v2" }] });
    renderPage();
    const entry = await screen.findByRole("listitem");
    // The list shows the user-entered friendly name; the type stays separate.
    expect(within(entry).getByText("Team gateway")).toBeInTheDocument();
    expect(within(entry).getByText("OpenCode")).toBeInTheDocument();
    expect(within(entry).getByText("Group")).toBeInTheDocument();
    expect(within(entry).getByText("Owner: alex")).toBeInTheDocument();
  });
});

describe("provider row actions", () => {
  const savedRow = { id: "p-1", name: "Team gateway", provider_type: "opencode", visibility: "group", verification_status: "unknown", owner_user_id: "alex", auth_present: false, format: "v2" };
  /** Routes POST calls by URL suffix; values may be payloads or functions. */
  function postRoutes(routes: Record<string, unknown>) {
    post.mockImplementation(async (url: string) => {
      const hit = Object.entries(routes).find(([suffix]) => url.endsWith(suffix));
      return hit ? hit[1] : { data: {} };
    });
  }
  beforeEach(() => {
    vi.clearAllMocks();
    get.mockResolvedValue({ data: [savedRow] });
    postRoutes({
      // The saved-config verification endpoints; verify-model is matched first
      // because "/config/verify" would otherwise be ambiguous with prefixes.
      "/config/verify-model": { data: { ok: true, latency_ms: 420, verification_id: "ver-9" } },
      "/config/verify": { data: { valid: true, violations: [], models: ["openai/gpt-4.1", "openai/gpt-4.1-mini"] } },
    });
    del.mockResolvedValue({ data: { provider: "opencode", deleted: true, configured: false } });
    patch.mockResolvedValue({ data: { id: "p-1", verification_status: "verified" } });
  });

  it("exposes accessible edit, test, and delete actions on every row", async () => {
    renderPage();
    const entry = await screen.findByRole("listitem");
    expect(within(entry).getByRole("button", { name: "Edit" })).toBeInTheDocument();
    expect(within(entry).getByRole("button", { name: "Test connection" })).toBeInTheDocument();
    expect(within(entry).getByRole("button", { name: "Delete" })).toBeInTheDocument();
  });

  it("reopens the wizard for the edited instance with the name prefilled", async () => {
    get.mockResolvedValueOnce({ data: [savedRow] }).mockResolvedValue({ data: [{ ...savedRow, name: "Renamed gateway" }] });
    renderPage();
    const entry = await screen.findByRole("listitem");
    await userEvent.click(within(entry).getByRole("button", { name: "Edit" }));
    // The wizard starts on the data step with the name prefilled and the
    // provider type locked away (the type step never renders).
    const nameInput = await screen.findByLabelText(/Configuration name/);
    expect(nameInput).toHaveValue("Team gateway");
    expect(screen.queryByRole("button", { name: /OpenCode/ })).not.toBeInTheDocument();
    // A rename-only save targets the row id and leaves the stored files alone.
    await userEvent.clear(nameInput);
    await userEvent.type(nameInput, "Renamed gateway");
    await userEvent.click(screen.getByRole("button", { name: "Continue" }));
    await userEvent.click(await screen.findByRole("button", { name: "Save provider" }));
    await waitFor(() => expect(patch).toHaveBeenCalledTimes(1));
    const submitted = patch.mock.calls[0][1].body as FormData;
    expect(submitted.get("config_id")).toBe("p-1");
    expect(submitted.get("name")).toBe("Renamed gateway");
    expect(submitted.get("opencode_json")).toBeNull();
    expect(submitted.get("verification_id")).toBeNull();
    // The list is refreshed after the edit completes.
    await waitFor(() => expect(get).toHaveBeenCalledTimes(2));
    expect(await screen.findByText("Renamed gateway")).toBeInTheDocument();
  });

  it("lists the saved configuration models, verifies the chosen one, and refreshes the status", async () => {
    get.mockResolvedValueOnce({ data: [savedRow] }).mockResolvedValue({ data: [{ ...savedRow, verification_status: "verified" }] });
    renderPage();
    await userEvent.click(await screen.findByRole("button", { name: "Test connection" }));
    const dialog = await screen.findByRole("dialog");
    // Models are listed from the SAVED configuration targeted by the row id.
    expect(post).toHaveBeenCalledWith("/providers/opencode/config/verify", { body: { config_id: "p-1" } });
    const select = (await within(dialog).findByLabelText("Discovered models")) as HTMLSelectElement;
    expect(select.value).toBe("openai/gpt-4.1");
    await userEvent.selectOptions(select, "openai/gpt-4.1-mini");
    await userEvent.click(within(dialog).getByRole("button", { name: "Test connection" }));
    expect(await within(dialog).findByText("Connection verified with openai/gpt-4.1-mini (420 ms).")).toBeInTheDocument();
    expect(post).toHaveBeenCalledWith("/providers/opencode/config/verify-model", { body: { model: "openai/gpt-4.1-mini", config_id: "p-1" } });
    // The list behind the dialog is re-fetched so the status column shows the
    // server-updated verification state without reloading the page.
    await screen.findByText("Verified");
    expect(get).toHaveBeenCalledTimes(2);
  });

  it("targets each row's own configuration when testing the connection", async () => {
    const otherRow = { ...savedRow, id: "p-2", name: "Personal gateway", visibility: "personal" };
    get.mockResolvedValue({ data: [savedRow, otherRow] });
    renderPage();
    const items = await screen.findAllByRole("listitem");
    await userEvent.click(within(items[0]).getByRole("button", { name: "Test connection" }));
    await within(await screen.findByRole("dialog")).findByLabelText("Discovered models");
    expect(post).toHaveBeenCalledWith("/providers/opencode/config/verify", { body: { config_id: "p-1" } });
    await userEvent.click(within(screen.getByRole("dialog")).getByRole("button", { name: "Close" }));
    await userEvent.click(within(items[1]).getByRole("button", { name: "Test connection" }));
    await within(await screen.findByRole("dialog")).findByLabelText("Discovered models");
    expect(post).toHaveBeenCalledWith("/providers/opencode/config/verify", { body: { config_id: "p-2" } });
  });

  it("renders the structured verification failure and still refreshes the status", async () => {
    postRoutes({
      "/config/verify-model": { error: { code: "VALIDATION_FAILED", message_key: "errors.provider.auth_missing", params: { provider: "opencode" }, details: [] } },
      "/config/verify": { data: { valid: true, violations: [], models: ["openai/gpt-4.1"] } },
    });
    renderPage();
    await userEvent.click(await screen.findByRole("button", { name: "Test connection" }));
    const dialog = await screen.findByRole("dialog");
    await within(dialog).findByLabelText("Discovered models");
    await userEvent.click(within(dialog).getByRole("button", { name: "Test connection" }));
    expect(await within(dialog).findByRole("alert")).toHaveTextContent("Add provider credentials before continuing.");
    // The server records the failed status even on a 422; the list is re-fetched.
    await waitFor(() => expect(get).toHaveBeenCalledTimes(2));
  });

  it("renders saved-config violations instead of a model picker when the configuration no longer validates", async () => {
    postRoutes({ "/config/verify": { data: { valid: false, violations: [{ message_key: "errors.provider.auth_missing", params: { provider: "opencode" } }], models: [] } } });
    renderPage();
    await userEvent.click(await screen.findByRole("button", { name: "Test connection" }));
    const dialog = await screen.findByRole("dialog");
    expect(await within(dialog).findByRole("alert")).toHaveTextContent("Add provider credentials before continuing.");
    expect(within(dialog).queryByLabelText("Discovered models")).not.toBeInTheDocument();
    // Discovery is read-only: the row status is left untouched.
    expect(get).toHaveBeenCalledTimes(1);
  });

  it("deletes the configuration after confirmation and refreshes the list", async () => {
    get.mockResolvedValueOnce({ data: [savedRow] }).mockResolvedValue({ data: [] });
    renderPage();
    await userEvent.click(await screen.findByRole("button", { name: "Delete" }));
    const confirmDialog = await screen.findByRole("alertdialog");
    expect(within(confirmDialog).getByText("This configuration and its stored files will be removed. This action cannot be undone.")).toBeInTheDocument();
    await userEvent.click(within(confirmDialog).getByRole("button", { name: "Delete" }));
    await waitFor(() => expect(del).toHaveBeenCalledWith("/providers/opencode/config", { params: { query: { config_id: "p-1" } } }));
    await waitFor(() => expect(get).toHaveBeenCalledTimes(2));
    await waitFor(() => expect(screen.queryByRole("listitem")).not.toBeInTheDocument());
  });

  it("surfaces a keyed delete failure and keeps the row", async () => {
    del.mockResolvedValue({ error: { code: "NOT_FOUND", message_key: "errors.provider.config_not_found", params: {}, details: [] } });
    renderPage();
    await userEvent.click(await screen.findByRole("button", { name: "Delete" }));
    const confirmDialog = await screen.findByRole("alertdialog");
    await userEvent.click(within(confirmDialog).getByRole("button", { name: "Delete" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Provider configuration not found.");
    expect(screen.getByRole("listitem")).toBeInTheDocument();
  });

  it("restores focus to the Test connection row action after its dialog closes", async () => {
    renderPage();
    const opener = await screen.findByRole("button", { name: "Test connection" });
    await userEvent.click(opener);
    const dialog = await screen.findByRole("dialog");
    await userEvent.click(within(dialog).getByRole("button", { name: "Close" }));
    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
    // The verify dialog is controlled without a trigger: it must still return
    // focus to the row action that opened it.
    expect(opener).toHaveFocus();
  });

  it("lands focus on a surviving row action after the deleted row disappears", async () => {
    const otherRow = { ...savedRow, id: "p-2", name: "Personal gateway", visibility: "personal" };
    get.mockResolvedValueOnce({ data: [savedRow, otherRow] }).mockResolvedValue({ data: [otherRow] });
    renderPage();
    const items = await screen.findAllByRole("listitem");
    await userEvent.click(within(items[0]).getByRole("button", { name: "Delete" }));
    await userEvent.click(within(await screen.findByRole("alertdialog")).getByRole("button", { name: "Delete" }));
    await waitFor(() => expect(screen.getAllByRole("listitem")).toHaveLength(1));
    // The opener row action died with its row; focus must land on a surviving
    // control (the row action of the row that now occupies the position),
    // never on the document body.
    await waitFor(() => {
      const focus = document.activeElement as HTMLElement | null;
      expect(focus).not.toBe(document.body);
      expect(focus?.closest("li")).toHaveTextContent("Personal gateway");
    });
  });

  it("lands focus on the page Add action when the deleted row was the only one", async () => {
    get.mockResolvedValueOnce({ data: [savedRow] }).mockResolvedValue({ data: [] });
    renderPage();
    await userEvent.click(await screen.findByRole("button", { name: "Delete" }));
    await userEvent.click(within(await screen.findByRole("alertdialog")).getByRole("button", { name: "Delete" }));
    await waitFor(() => expect(screen.queryByRole("listitem")).not.toBeInTheDocument());
    await waitFor(() => expect(screen.getByRole("button", { name: "Add" })).toHaveFocus());
  });

  it("keeps the Test connection label with aria-busy while the verification is in flight", async () => {
    let resolveVerifyModel: (value: unknown) => void = () => {};
    const pendingVerifyModel = new Promise((resolve) => { resolveVerifyModel = resolve; });
    postRoutes({
      "/config/verify-model": pendingVerifyModel,
      "/config/verify": { data: { valid: true, violations: [], models: ["openai/gpt-4.1"] } },
    });
    renderPage();
    await userEvent.click(await screen.findByRole("button", { name: "Test connection" }));
    const dialog = await screen.findByRole("dialog");
    await within(dialog).findByLabelText("Discovered models");
    await userEvent.click(within(dialog).getByRole("button", { name: "Test connection" }));
    const confirm = within(dialog).getByRole("button", { name: "Test connection" });
    expect(confirm).toHaveAttribute("aria-busy", "true");
    expect(confirm).toBeDisabled();
    // The label stays put; only the shared spinner and aria-busy signal flight.
    expect(confirm).toHaveTextContent("Test connection");
    expect(confirm).not.toHaveTextContent("Testing…");
    resolveVerifyModel({ data: { ok: true, latency_ms: 420, verification_id: "ver-9" } });
    await waitFor(() => expect(confirm).not.toBeDisabled());
  });
});

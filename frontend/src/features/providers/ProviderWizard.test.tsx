import { beforeEach, describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { ProviderAuthMethod } from "./capabilities";

const { get, post, put } = vi.hoisted(() => ({ get: vi.fn(), post: vi.fn(), put: vi.fn() }));
vi.mock("@/api/auth", () => ({ api: { GET: get, POST: post, PUT: put } }));
let mockCapabilities: any;
vi.mock("@/features/auth/useCurrentUser", () => ({ useCurrentUser: () => ({ user: { username: "alex" }, capabilities: mockCapabilities, loading: false, error: null }) }));

/**
 * Auth methods offered by OpenCode; mutable so a test can exercise the
 * auth-method step, which only exists for providers with several methods.
 */
const capabilityOverrides = vi.hoisted(() => ({ opencodeMethods: ["config"] as string[] }));
vi.mock("./capabilities", async (importOriginal) => {
  const actual = await importOriginal<typeof import("./capabilities")>();
  return {
    ...actual,
    get providerCapabilities() {
      return actual.providerCapabilities.map((item) =>
        item.type === "opencode" ? { ...item, authMethods: capabilityOverrides.opencodeMethods as ProviderAuthMethod[] } : item,
      );
    },
  };
});

import { ProviderWizard } from "./ProviderWizard";

const validConfig = JSON.stringify({ provider: { openai: { options: {}, models: { "gpt-4.1": {} } } } });
const validConfigObject = JSON.parse(validConfig);
const authObject = { opencode: { type: "api", key: "k-1" } };
const jsoncConfig = `{\n  // primary provider\n  "provider": { /* inline */ "openai": { "options": {}, "models": { "gpt-4.1": {} } }, },\n}`;
const dropzoneName = "Drag and drop your configuration file here, or browse to choose it";
const authDropzoneName = "Drag and drop auth.json here, or browse to choose it";
const verifySuccess = { ok: true, response_snippet: "ok", latency_ms: 420, verification_id: "ver-1" };

const DEFAULT_POST_ROUTES: Record<string, unknown> = {
  "/candidate/validate": { data: { valid: true, violations: [] } },
  "/candidate/models": { data: { valid: true, violations: [], models: ["openai/gpt-4.1", "openai/gpt-4.1-mini"] } },
  "/candidate/verify-model": { data: verifySuccess },
};

/** Routes POST calls by URL suffix; route values may be payloads, promises or functions. */
function postRoutes(routes: Record<string, unknown> = {}) {
  post.mockImplementation(async (url: string) => {
    const hit = Object.entries(routes).find(([suffix]) => url.endsWith(suffix));
    if (hit) return typeof hit[1] === "function" ? await (hit[1] as (u: string) => unknown)(url) : hit[1];
    const fallback = Object.entries(DEFAULT_POST_ROUTES).find(([suffix]) => url.endsWith(suffix));
    return fallback ? fallback[1] : { data: {} };
  });
}

/** Body of the first POST whose URL ends with the given suffix. */
function postedTo(suffix: string) {
  const call = post.mock.calls.find(([url]) => String(url).endsWith(suffix));
  if (!call) throw new Error(`No POST call to ${suffix}`);
  return call[1];
}

function renderWizard() {
  return render(<ProviderWizard onCancel={() => {}} onComplete={() => {}} />);
}
function makeFile(content: string, name: string, type = "application/json") {
  return new File([content], name, { type });
}
function dropFile(zone: Element, file: File) {
  fireEvent.drop(zone, { dataTransfer: { files: [file] } });
}
function configDropzone() {
  const input = screen.getByLabelText(dropzoneName);
  return input.closest("label") ?? input;
}
async function toUploadStep() {
  await userEvent.click(screen.getByRole("button", { name: /OpenCode/ }));
  await userEvent.click(screen.getByRole("button", { name: "Continue" }));
  expect(await screen.findByLabelText(dropzoneName)).toBeInTheDocument();
}
/** Selects a configuration through the file picker (the only upload path). */
async function chooseConfig(content: string, name = "opencode.json") {
  await userEvent.upload(screen.getByLabelText(dropzoneName), makeFile(content, name));
  await screen.findByText(`Selected file: ${name}`);
}
/** Types the mandatory friendly name on the data step. */
async function fillName(value = "Personal gateway") {
  await userEvent.type(screen.getByLabelText(/Configuration name/), value);
}
async function toTestStep() {
  await toUploadStep();
  await chooseConfig(validConfig);
  await fillName();
  await userEvent.click(screen.getByRole("button", { name: "Continue" }));
  await screen.findByRole("heading", { name: "Test the connection" });
}
async function runSuccessfulTest(model = "openai/gpt-4.1-mini") {
  await userEvent.selectOptions(screen.getByLabelText("Discovered models"), model);
  await userEvent.click(screen.getByRole("button", { name: "Test connection" }));
  await screen.findByText(`Connection verified with ${model} (420 ms).`);
}

describe("provider wizard", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    capabilityOverrides.opencodeMethods = ["config"];
    mockCapabilities = { scopes: { personal: true, groups: [], global: false }, groups: [] };
    postRoutes();
    put.mockResolvedValue({ data: { id: "new-provider" } });
  });

  it("pairs a decorative icon with each provider name on the type step", async () => {
    renderWizard();
    for (const name of [/OpenCode/, /Claude Code/, /Codex/]) {
      const card = screen.getByRole("button", { name });
      expect(card.querySelector("svg[aria-hidden='true']")).toBeInTheDocument();
    }
  });

  it("skips the auth-method step for a provider with a single configuration method", async () => {
    renderWizard();
    await userEvent.click(screen.getByRole("button", { name: /OpenCode/ }));
    await userEvent.click(screen.getByRole("button", { name: "Continue" }));
    expect(await screen.findByRole("heading", { name: "Add your configuration" })).toBeInTheDocument();
    expect(screen.queryByText("Step 2 of 5")).not.toBeInTheDocument();
    expect(await screen.findByText("Step 2 of 4")).toBeInTheDocument();
  });

  it("shows the auth-method step only when the provider offers several methods", async () => {
    capabilityOverrides.opencodeMethods = ["api_key", "config"];
    renderWizard();
    await userEvent.click(screen.getByRole("button", { name: /OpenCode/ }));
    await userEvent.click(screen.getByRole("button", { name: "Continue" }));
    expect(await screen.findByRole("heading", { name: "Choose a configuration method" })).toBeInTheDocument();
    expect(screen.getByText("Step 2 of 5")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: /Configuration file/ }));
    await userEvent.click(screen.getByRole("button", { name: "Continue" }));
    expect(await screen.findByRole("heading", { name: "Add your configuration" })).toBeInTheDocument();
  });

  it("requires a friendly name before leaving the data step", async () => {
    renderWizard();
    await toUploadStep();
    const nameInput = screen.getByLabelText(/Configuration name/) as HTMLInputElement;
    expect(nameInput.value).toBe(""); // no default and never the provider type
    expect(nameInput.maxLength).toBe(80);
    await chooseConfig(validConfig);
    expect(screen.getByRole("button", { name: "Continue" })).toBeDisabled();
    await userEvent.type(nameInput, "   ");
    expect(screen.getByRole("button", { name: "Continue" })).toBeDisabled();
    await userEvent.clear(nameInput);
    await fillName();
    expect(screen.getByRole("button", { name: "Continue" })).toBeEnabled();
  });

  it("sends the trimmed friendly name with the save request", async () => {
    renderWizard();
    await toUploadStep();
    await chooseConfig(validConfig);
    await fillName("  Team gateway  ");
    await userEvent.click(screen.getByRole("button", { name: "Continue" }));
    await screen.findByRole("heading", { name: "Test the connection" });
    await runSuccessfulTest("openai/gpt-4.1");
    await userEvent.click(screen.getByRole("button", { name: "Continue" }));
    await userEvent.click(await screen.findByRole("button", { name: "Save provider" }));
    await waitFor(() => expect(put).toHaveBeenCalledTimes(1));
    const submitted = put.mock.calls[0][1].body as FormData;
    expect(submitted.get("name")).toBe("Team gateway");
  });

  it("exposes a keyboard-reachable file picker that accepts .json and .jsonc", async () => {
    renderWizard();
    await toUploadStep();
    const input = screen.getByLabelText(dropzoneName) as HTMLInputElement;
    expect(input).toHaveAttribute("type", "file");
    expect(input).toHaveAttribute("accept", ".json,.jsonc,application/json");
    input.focus();
    expect(input).toHaveFocus();
    await screen.findByText("Accepted formats: .json or .jsonc (up to 1 MB).");
  });

  it("loads a dropped .jsonc file, strips comments, and validates it as JSON", async () => {
    renderWizard();
    await toUploadStep();
    dropFile(configDropzone(), makeFile(jsoncConfig, "opencode.jsonc"));
    expect(await screen.findByText("Selected file: opencode.jsonc")).toBeInTheDocument();
    await fillName();
    await userEvent.click(screen.getByRole("button", { name: "Continue" }));
    await screen.findByRole("heading", { name: "Test the connection" });
    expect(postedTo("/candidate/validate")).toEqual({ body: { config: validConfigObject } });
  });

  it("loads a chosen .json file through the picker", async () => {
    renderWizard();
    await toUploadStep();
    await userEvent.upload(screen.getByLabelText(dropzoneName), makeFile(validConfig, "opencode.json"));
    expect(await screen.findByText("Selected file: opencode.json")).toBeInTheDocument();
    await fillName();
    await userEvent.click(screen.getByRole("button", { name: "Continue" }));
    expect(await screen.findByRole("heading", { name: "Test the connection" })).toBeInTheDocument();
  });

  it("rejects .js files with a localized error and no API call", async () => {
    renderWizard();
    await toUploadStep();
    dropFile(configDropzone(), makeFile("{}", "payload.js", "text/javascript"));
    expect(await screen.findByRole("alert")).toHaveTextContent("payload.js is not a JSON file. Choose a .json or .jsonc file.");
    expect(post).not.toHaveBeenCalled();
  });

  it("rejects oversized files with a localized error and no API call", async () => {
    renderWizard();
    await toUploadStep();
    dropFile(configDropzone(), makeFile("x".repeat(1_000_001), "opencode.json"));
    expect(await screen.findByRole("alert")).toHaveTextContent("opencode.json is larger than 1 MB. Choose a smaller file.");
    expect(post).not.toHaveBeenCalled();
  });

  it("reports unreadable files with a localized error and no API call", async () => {
    renderWizard();
    await toUploadStep();
    const file = makeFile("{}", "broken.json");
    vi.spyOn(file, "text").mockRejectedValue(new Error("disk error"));
    dropFile(configDropzone(), file);
    expect(await screen.findByRole("alert")).toHaveTextContent("broken.json could not be read. Try again.");
    expect(post).not.toHaveBeenCalled();
  });

  it("reports malformed file contents as invalid JSON", async () => {
    renderWizard();
    await toUploadStep();
    dropFile(configDropzone(), makeFile("not json", "opencode.json"));
    expect(await screen.findByRole("alert")).toHaveTextContent("opencode.json must contain a valid JSON object.");
    expect(post).not.toHaveBeenCalled();
  });

  it("sends the selected auth to candidate validation and model discovery", async () => {
    renderWizard();
    await toUploadStep();
    await chooseConfig(validConfig);
    await userEvent.upload(screen.getByLabelText(authDropzoneName), makeFile(JSON.stringify(authObject), "auth.json"));
    expect(await screen.findByText("Credentials file selected: auth.json")).toBeInTheDocument();
    await fillName();
    await userEvent.click(screen.getByRole("button", { name: "Continue" }));
    await screen.findByRole("heading", { name: "Test the connection" });
    expect(postedTo("/candidate/validate")).toEqual({ body: { config: validConfigObject, auth: authObject } });
    expect(postedTo("/candidate/models")).toEqual({ body: { config: validConfigObject, auth: authObject } });
  });

  it("requires the credentials file to be named auth.json", async () => {
    renderWizard();
    await toUploadStep();
    await chooseConfig(validConfig);
    fireEvent.change(screen.getByLabelText(authDropzoneName), { target: { files: [makeFile("{}", "creds.json")] } });
    expect(await screen.findByRole("alert")).toHaveTextContent("The credentials file must be named auth.json.");
    expect(post).not.toHaveBeenCalled();
  });

  it("stops sending auth after the credentials file is removed", async () => {
    renderWizard();
    await toUploadStep();
    await chooseConfig(validConfig);
    await userEvent.upload(screen.getByLabelText(authDropzoneName), makeFile(JSON.stringify(authObject), "auth.json"));
    await fillName();
    await userEvent.click(screen.getByRole("button", { name: "Continue" }));
    await screen.findByRole("heading", { name: "Test the connection" });
    await userEvent.click(screen.getByRole("button", { name: "Back" }));
    await userEvent.click(await screen.findByRole("button", { name: "Remove credentials file" }));
    expect(screen.queryByText("Credentials file selected: auth.json")).not.toBeInTheDocument();
    expect(screen.getByLabelText(authDropzoneName)).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Continue" }));
    await screen.findByRole("heading", { name: "Test the connection" });
    const validateCalls = post.mock.calls.filter(([url]) => String(url).endsWith("/candidate/validate"));
    expect(validateCalls).toHaveLength(2);
    expect(validateCalls[1][1]).toEqual({ body: { config: validConfigObject } });
  });

  it("blocks progress until the connection test succeeds", async () => {
    renderWizard();
    await toTestStep();
    const testButton = screen.getByRole("button", { name: "Test connection" });
    expect(testButton).toBeEnabled();
    expect(screen.queryByRole("button", { name: "Continue" })).not.toBeInTheDocument();
    await userEvent.click(testButton);
    await screen.findByText("Connection verified with openai/gpt-4.1 (420 ms).");
    expect(screen.getByRole("button", { name: "Continue" })).toBeEnabled();
    expect(screen.queryByRole("heading", { name: "Choose who can use it" })).not.toBeInTheDocument();
  });

  it("verifies the selected model with the candidate verify-model endpoint", async () => {
    renderWizard();
    await toUploadStep();
    await chooseConfig(validConfig);
    await userEvent.upload(screen.getByLabelText(authDropzoneName), makeFile(JSON.stringify(authObject), "auth.json"));
    await fillName();
    await userEvent.click(screen.getByRole("button", { name: "Continue" }));
    await screen.findByRole("heading", { name: "Test the connection" });
    await runSuccessfulTest("openai/gpt-4.1-mini");
    expect(postedTo("/candidate/verify-model")).toEqual({
      body: { config: validConfigObject, auth: authObject, model: "openai/gpt-4.1-mini" },
    });
  });

  it("renders the structured verification failure and keeps the test available", async () => {
    postRoutes({ "/candidate/verify-model": { data: { ok: false, error: { code: "PROVIDER_VERIFICATION_FAILED", message_key: "errors.provider.verification_failed", params: { reason: "Boom" } } } } });
    renderWizard();
    await toTestStep();
    await userEvent.click(screen.getByRole("button", { name: "Test connection" }));
    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent("Provider verification failed.");
    expect(screen.queryByText(/Connection verified with/)).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Test connection" })).toBeEnabled();
    expect(screen.queryByRole("button", { name: "Continue" })).not.toBeInTheDocument();
  });

  it("surfaces HTTP-level verification errors instead of masking them", async () => {
    // Mirrors the live wire contract: flat KosmoError body on HTTP 422.
    postRoutes({ "/candidate/verify-model": { error: { code: "VALIDATION_FAILED", message_key: "errors.provider.verification_timeout", params: {}, details: [] } } });
    renderWizard();
    await toTestStep();
    await userEvent.click(screen.getByRole("button", { name: "Test connection" }));
    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent("Provider verification timed out.");
    expect(alert).not.toHaveTextContent("An unexpected error occurred.");
    expect(screen.getByRole("button", { name: "Test connection" })).toBeEnabled();
  });

  it("replaces the previous verification when a different model is tested", async () => {
    let run = 0;
    postRoutes({ "/candidate/verify-model": async () => { run += 1; return { data: { ...verifySuccess, verification_id: `ver-${run}` } }; } });
    renderWizard();
    await toTestStep();
    await runSuccessfulTest("openai/gpt-4.1");
    await userEvent.selectOptions(screen.getByLabelText("Discovered models"), "openai/gpt-4.1-mini");
    expect(screen.getByText("Now selected: openai/gpt-4.1-mini. Run the test again to verify it.")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Test connection" }));
    await screen.findByText("Connection verified with openai/gpt-4.1-mini (420 ms).");
    await userEvent.click(screen.getByRole("button", { name: "Continue" }));
    await userEvent.click(await screen.findByRole("button", { name: "Save provider" }));
    await waitFor(() => expect(put).toHaveBeenCalledTimes(1));
    const submitted = put.mock.calls[0][1].body as FormData;
    expect(submitted.get("verification_id")).toBe("ver-2");
  });

  it("commits auth_json and verification_id in the multipart upload and never sends selected_model", async () => {
    renderWizard();
    await toUploadStep();
    await chooseConfig(validConfig);
    await userEvent.upload(screen.getByLabelText(authDropzoneName), makeFile(JSON.stringify(authObject), "auth.json"));
    await fillName();
    await userEvent.click(screen.getByRole("button", { name: "Continue" }));
    await screen.findByRole("heading", { name: "Test the connection" });
    await runSuccessfulTest("openai/gpt-4.1-mini");
    await userEvent.click(screen.getByRole("button", { name: "Continue" }));
    expect(await screen.findByText("Connection verified with openai/gpt-4.1-mini.")).toBeInTheDocument();
    expect(screen.getByText("OpenCode · owned by alex")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Save provider" }));
    await waitFor(() => expect(put).toHaveBeenCalledTimes(1));
    const submitted = put.mock.calls[0][1].body as FormData;
    expect(submitted.get("name")).toBe("Personal gateway");
    expect(submitted.get("selected_model")).toBeNull();
    expect(submitted.get("verification_id")).toBe("ver-1");
    expect(submitted.get("visibility")).toBe("personal");
    const configPart = submitted.get("opencode_json") as File;
    expect(configPart.name).toBe("opencode.json");
    expect(JSON.parse(await configPart.text())).toEqual(validConfigObject);
    const authPart = submitted.get("auth_json") as File;
    expect(authPart.name).toBe("auth.json");
    expect(JSON.parse(await authPart.text())).toEqual(authObject);
  });

  it("omits verification_id when the backend returns no verification proof", async () => {
    postRoutes({ "/candidate/verify-model": { data: { ok: true, response_snippet: "ok", latency_ms: 5 } } });
    renderWizard();
    await toTestStep();
    await userEvent.click(screen.getByRole("button", { name: "Test connection" }));
    await screen.findByText("Connection verified with openai/gpt-4.1 (5 ms).");
    await userEvent.click(screen.getByRole("button", { name: "Continue" }));
    await screen.findByRole("heading", { name: "Choose who can use it" });
    await userEvent.click(screen.getByRole("button", { name: "Save provider" }));
    await waitFor(() => expect(put).toHaveBeenCalledTimes(1));
    const submitted = put.mock.calls[0][1].body as FormData;
    expect(submitted.get("verification_id")).toBeNull();
    expect(submitted.get("selected_model")).toBeNull();
  });

  it("clears the verification result when the configuration changes", async () => {
    renderWizard();
    await toTestStep();
    await runSuccessfulTest("openai/gpt-4.1");
    await userEvent.click(screen.getByRole("button", { name: "Back" }));
    await chooseConfig(validConfig);
    await userEvent.click(screen.getByRole("button", { name: "Continue" }));
    await screen.findByRole("heading", { name: "Test the connection" });
    expect(screen.queryByText(/Connection verified with/)).not.toBeInTheDocument();
    expect(screen.getByLabelText("Discovered models")).toHaveValue("openai/gpt-4.1");
    expect(screen.getByRole("button", { name: "Test connection" })).toBeEnabled();
    expect(screen.queryByRole("button", { name: "Continue" })).not.toBeInTheDocument();
  });

  it("clears the verification result when the credentials file changes", async () => {
    renderWizard();
    await toUploadStep();
    await chooseConfig(validConfig);
    await userEvent.upload(screen.getByLabelText(authDropzoneName), makeFile(JSON.stringify(authObject), "auth.json"));
    await fillName();
    await userEvent.click(screen.getByRole("button", { name: "Continue" }));
    await screen.findByRole("heading", { name: "Test the connection" });
    await runSuccessfulTest("openai/gpt-4.1");
    await userEvent.click(screen.getByRole("button", { name: "Back" }));
    await userEvent.click(await screen.findByRole("button", { name: "Remove credentials file" }));
    await userEvent.upload(screen.getByLabelText(authDropzoneName), makeFile(JSON.stringify(authObject), "auth.json"));
    await userEvent.click(screen.getByRole("button", { name: "Continue" }));
    await screen.findByRole("heading", { name: "Test the connection" });
    expect(screen.queryByText(/Connection verified with/)).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Continue" })).not.toBeInTheDocument();
  });

  it("shows the empty-model message and disables testing when no models are discovered", async () => {
    postRoutes({ "/candidate/models": { data: { valid: true, violations: [], models: [] } } });
    renderWizard();
    await toUploadStep();
    await chooseConfig(validConfig);
    await fillName();
    await userEvent.click(screen.getByRole("button", { name: "Continue" }));
    await screen.findByRole("heading", { name: "Test the connection" });
    expect(await screen.findByText("No models were found for this configuration.")).toBeInTheDocument();
    expect(screen.queryByLabelText("Discovered models")).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Test connection" })).toBeDisabled();
  });

  it("discards stale model discovery when the configuration changes mid-request", async () => {
    renderWizard();
    await toUploadStep();
    await chooseConfig(validConfig);
    let resolveModels!: (value: unknown) => void;
    postRoutes({ "/candidate/models": new Promise((resolve) => { resolveModels = resolve; }) });
    await fillName();
    await userEvent.click(screen.getByRole("button", { name: "Continue" }));
    await waitFor(() => expect(post).toHaveBeenCalledTimes(2));
    await chooseConfig(validConfig);
    resolveModels({ data: { valid: true, violations: [], models: ["openai/gpt-4.1"] } });
    await waitFor(() => expect(screen.getByRole("button", { name: "Continue" })).toBeEnabled());
    expect(screen.getByRole("heading", { name: "Add your configuration" })).toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: "Test the connection" })).not.toBeInTheDocument();
  });

  it("surfaces candidate model discovery unavailability instead of masking it", async () => {
    // Mirrors the live wire contract: flat KosmoError body on HTTP 422.
    postRoutes({ "/candidate/models": { error: { code: "VALIDATION_FAILED", message_key: "errors.provider.candidate_operation_unavailable", params: {}, details: [] } } });
    renderWizard();
    await toUploadStep();
    await chooseConfig(validConfig);
    await fillName();
    await userEvent.click(screen.getByRole("button", { name: "Continue" }));
    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent("Model discovery is temporarily unavailable. Try again later.");
    expect(alert).not.toHaveTextContent("An unexpected error occurred.");
    expect(screen.getByRole("heading", { name: "Add your configuration" })).toBeInTheDocument();
  });
});

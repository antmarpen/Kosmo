// Phase-2 Playwright acceptance journeys for the compose stack (R9).
//
// Requirements covered:
//   AC-P2-01: Provider onboarding row actions — synthetic configs created via
//             the API; row "Test connection" targets the clicked row (asserted
//             on the captured verify request body); delete asks for
//             confirmation.  The owner's credentials are never used: rows are
//             created with synthetic keys and removed afterwards.
//   AC-P2-04: Launch a workflow — create a task from /tasks/new with the
//             seeded reference workflow and follow it to a terminal state.
//   AC-P2-04: Workflow authoring — build a Start→Script→AI→End graph in the
//             editor, save the draft, publish it, activate it.
//   AC-P2-06: Publishing alone must not change the active version; the
//             default-off "Activate after publishing" option must activate.
//   AC-P2-10: English and Spanish paths for the new labels.
//
// Credential-dependent journeys (a real model call) are gated and documented:
//   Prerequisite: export OPENCODE_API_KEY (or KOSMO_E2E_OPENCODE_API_KEY)
//   before running.  Without it the journey is reported as SKIPPED with a
//   reason — never as passing.  The key is used to build a throwaway provider
//   configuration and is never printed, logged, or committed by the test.
//
// Prerequisites for the executable journeys:
//   - The compose stack is up and seeded (`just up`, `just seed`): accounts
//     test-runner/runner-change-me and admin/admin-change-me exist and the
//     reference-security-analysis workflow has an active version.
//   - OPENCODE_API_KEY is NOT required: without credentials the launched task
//     still reaches the "failed" terminal state through the structured
//     agent-auth-missing branch, which the journey accepts and verifies.
//
// Run against a running compose stack:
//   just e2e
//   pnpm -C frontend e2e

import { expect, test, type APIRequestContext, type Page } from "@playwright/test";

// ─── Environment ───────────────────────────────────────────────────────────────

const username = process.env.KOSMO_E2E_USERNAME ?? "test-runner";
const password = process.env.KOSMO_E2E_PASSWORD ?? "runner-change-me";

// Workflow authoring and publishing require the builder or admin role
// (require_roles): the seeded runner account cannot create workflows, so the
// authoring journeys use the seeded admin account. Values are never printed.
const adminUsername = process.env.KOSMO_E2E_ADMIN_USERNAME ?? "admin";
const adminPassword = process.env.KOSMO_E2E_ADMIN_PASSWORD ?? "admin-change-me";

const runnerCredentials = { username, password };
const adminCredentials = { username: adminUsername, password: adminPassword };

/** Unique suffix for globally-unique names: Date.now() alone has actually
 *  collided between two back-to-back executions (workflow names are globally
 *  case-insensitively unique), so a random component is mandatory. */
function uniqueSuffix(): string {
  return `${Date.now()}-${Math.random().toString(36).slice(2, 8)}`;
}

// Credential-gated prerequisite: a real provider key enabling a real model call.
const providerKey = process.env.KOSMO_E2E_OPENCODE_API_KEY ?? process.env.OPENCODE_API_KEY;

const TERMINAL_TASK_STATES = ["success", "failed", "stopped", "waiting_for_input"];

// ─── Auth helpers ──────────────────────────────────────────────────────────────

async function login(page: Page, credentials = runnerCredentials): Promise<void> {
  await page.goto("/login");
  await expect(page.getByRole("heading", { name: /sign in|iniciar sesión/i })).toBeVisible({
    timeout: 15_000,
  });
  await page.getByLabel(/username|usuario/i).fill(credentials.username);
  await page.getByLabel(/password|contraseñ?a/i).fill(credentials.password);
  await page.getByRole("button", { name: /sign in|iniciar sesión/i }).click();
  // Default authenticated destination (resolveAuthenticatedDestination).
  await expect(page).toHaveURL(/\/tasks/, { timeout: 15_000 });
}

/** Bearer token for the backend through the frontend /api proxy. */
async function apiToken(request: APIRequestContext, credentials = runnerCredentials): Promise<string> {
  const response = await request.post("/api/auth/login", {
    data: credentials,
  });
  if (!response.ok()) throw new Error(`API login failed: ${response.status()} ${await response.text()}`);
  return (await response.json()).access_token as string;
}

function authed(token: string): Record<string, string> {
  return { Authorization: `Bearer ${token}` };
}

// ─── Synthetic provider helpers (never the owner's credentials) ───────────────

type ProviderRow = { id: string; name: string };

function syntheticSecret(): string {
  return `e2e-synthetic-${Date.now()}-${Math.random().toString(36).slice(2, 10)}`;
}

/** Creates one synthetic personal provider configuration via the API. */
async function createSyntheticProvider(
  request: APIRequestContext,
  token: string,
  name: string,
  files?: { config: unknown; auth: unknown },
): Promise<ProviderRow> {
  const config = files?.config ?? { providers: { opencode: { options: {} } } };
  const auth = files?.auth ?? [{
    id: `cred_e2e_${uniqueSuffix()}`,
    integrationID: "opencode",
    label: "API key",
    active: true,
    value: { type: "key", key: syntheticSecret() },
  }];
  const response = await request.put("/api/providers/opencode/config", {
    headers: authed(token),
    multipart: {
      name,
      visibility: "personal",
      opencode_json: {
        name: "opencode.json",
        mimeType: "application/json",
        buffer: Buffer.from(JSON.stringify(config)),
      },
      auth_json: {
        name: "auth.json",
        mimeType: "application/json",
        buffer: Buffer.from(JSON.stringify(auth)),
      },
    },
  });
  if (!response.ok()) throw new Error(`Create provider failed: ${response.status()} ${await response.text()}`);
  const created = (await response.json()) as { id: string; name: string };
  return { id: created.id, name: created.name };
}

async function deleteProvider(request: APIRequestContext, token: string, configId: string): Promise<void> {
  await request.delete("/api/providers/opencode/config", {
    params: { config_id: configId },
    headers: authed(token),
  });
}

// ─── Task helpers ──────────────────────────────────────────────────────────────

type TaskPayload = { state: string; notes?: { message_key: string }[] };

/** Polls the task API until it reaches a terminal state (or times out). */
async function waitTerminalTask(
  request: APIRequestContext,
  token: string,
  taskId: string,
  timeoutMs = 600_000,
): Promise<TaskPayload> {
  const deadline = Date.now() + timeoutMs;
  let lastState = "unknown";
  while (Date.now() < deadline) {
    const response = await request.get(`/api/tasks/${taskId}`, { headers: authed(token) });
    if (response.ok()) {
      const payload = (await response.json()) as { task?: TaskPayload } & TaskPayload;
      const task = payload.task ?? payload;
      lastState = task.state;
      if (TERMINAL_TASK_STATES.includes(task.state)) return task;
    }
    await new Promise((resolve) => setTimeout(resolve, 2_000));
  }
  throw new Error(`Task ${taskId} did not reach a terminal state (last state: ${lastState})`);
}

// ─── Workflow editor helpers ───────────────────────────────────────────────────

/** Creates a uniquely named workflow through the list page dialog. */
async function createWorkflow(page: Page, name: string): Promise<string> {
  await page.goto("/workflows");
  await expect(page.getByRole("heading", { name: /workflows|flujos de trabajo/i })).toBeVisible({
    timeout: 15_000,
  });
  await page.getByRole("button", { name: /^add$|añadir$/i }).first().click();
  const nameInput = page.getByLabel(/^name$|nombre$/i);
  await expect(nameInput).toBeVisible({ timeout: 10_000 });
  await nameInput.fill(name);
  await page.getByRole("button", { name: /create workflow|crear flujo de trabajo/i }).click();
  await page.waitForURL(/\/workflows\/[0-9a-f-]{36}\/edit/, { timeout: 30_000 });
  const workflowId = page.url().match(/\/workflows\/([0-9a-f-]{36})/)?.[1];
  if (!workflowId) throw new Error(`Editor URL missing workflow id: ${page.url()}`);
  await expect(page.getByLabel(/workflow name|nombre del flujo/i)).toBeVisible({ timeout: 15_000 });
  return workflowId;
}

/**
 * Commits script code through the modal editor (lazy Monaco chunk) and falls
 * back to the plain-text textarea when the chunk fails to load.
 */
async function fillScriptCode(page: Page, code: string): Promise<void> {
  await page.getByRole("button", { name: /edit script|editar script/i }).click();
  const dialog = page.getByRole("dialog");
  await expect(dialog).toBeVisible({ timeout: 15_000 });
  const monaco = dialog.locator(".monaco-editor");
  const loaded = await monaco.waitFor({ state: "visible", timeout: 30_000 }).then(() => true).catch(() => false);
  if (loaded) {
    await monaco.click();
    await page.keyboard.type(code);
  } else {
    await dialog.getByLabel(/^code$|código$/i).fill(code);
  }
  await dialog.getByRole("button", { name: /^save$|guardar$/i }).click();
  await expect(dialog).not.toBeVisible({ timeout: 15_000 });
}

/** Connects two canvas nodes by dragging from the source to the target handle. */
async function connectNodes(page: Page, source: string, target: string): Promise<void> {
  const sourceHandle = page.locator(`.react-flow__node[data-id="${source}"] .react-flow__handle.source`);
  const targetHandle = page.locator(`.react-flow__node[data-id="${target}"] .react-flow__handle.target`);
  await sourceHandle.hover();
  await page.mouse.down();
  await targetHandle.hover();
  await page.mouse.up();
}

/** Moves a canvas node by a pixel delta (relative, so no coordinate math).
 *  The hover asserts the card is actually grabbable: a silent miss would
 *  leave it covering another node's handle. */
async function dragNodeBy(page: Page, node: ReturnType<Page["locator"]>, dx: number, dy: number): Promise<void> {
  const box = await node.boundingBox();
  if (!box) throw new Error("Node bounding box unavailable");
  await node.hover();
  await page.mouse.down();
  await page.mouse.move(box.x + box.width / 2 + dx, box.y + box.height / 2 + dy, { steps: 8 });
  await page.mouse.up();
}

/** Saves the draft and waits for the saved indicator in the editor header. */
async function saveDraft(page: Page): Promise<void> {
  await page.getByRole("button", { name: /^save draft$|^guardar borrador$/i }).click();
  // Anchor the match: "Unsaved changes" also contains "saved".
  await expect(page.locator("header [role='status']")).toHaveText(/^(Saved|Guardado)$/, { timeout: 30_000 });
}

/** Refits the canvas via the editor's own button (the React Flow Controls
 *  widget ships a case-differing "Fit View" button, hence exact matching).
 *  fitView animates the viewport, so the wait lets it settle before the
 *  caller reads node geometry. */
async function fitView(page: Page): Promise<void> {
  await page.getByRole("button", { name: "Fit view", exact: true }).click();
  await page.waitForTimeout(400);
}

/** The reset seed now supplies a global reference agent; inline-agent authoring is obsolete. */
async function chooseReferenceAgent(page: Page): Promise<void> {
  const selector = page.getByRole("combobox", { name: /agent|agente/i });
  await expect(selector).toBeVisible();
  await selector.fill("reference-security-analysis-agent");
  await page.getByRole("option", { name: "reference-security-analysis-agent" }).click();
}

/**
 * Authors the Start→Script→AI→End graph through the real UI: palette adds,
 * properties panel forms (Start input field, script code, AI model/prompt),
 * canvas connections, and a unique workflow rename.
 */
async function authorReferenceGraph(page: Page, workflowName: string): Promise<void> {
  await page.getByLabel(/workflow name|nombre del flujo/i).fill(workflowName);

  // Add Script (palette button, selected on add) and commit its code.
  await page.getByRole("button", { name: /^add script$|añadir script$/i }).click();
  await fillScriptCode(page, "report = f'Security analysis for {topic}'\ndata = {'topic': topic}\nreturn report, data");

  // AI nodes now reference the seeded catalog agent; there is no inline model
  // or instructions configuration on the node.
  await page.getByRole("button", { name: /^add ai$|añadir ia$/i }).click();
  await chooseReferenceAgent(page);
  await page.getByLabel(/prompt template|plantilla de prompt/i).fill("Summarize the topic.");

  // AI output validation belongs to each declared output, not a node-level
  // inline validation list.
  await page.getByRole("button", { name: /^add output$|^añadir salida$/i }).click();
  await page.getByLabel(/^outputs 1$/i).fill("summary");
  await page.getByRole("button", { name: /validation.*summary/i }).click();
  const validationDialog = page.getByRole("dialog");
  await validationDialog.getByLabel(/format/i).selectOption("markdown");
  // Markdown is parse-only in the round-2 contract: no schema and no rules.
  await validationDialog.getByRole("button", { name: /save|guardar/i }).click();
  await expect(validationDialog).not.toBeVisible();

  // The blank editor seeds Start+End apart but stacks AI over Script: refit
  // the view, then drag the AI card clear of the Script card (node text
  // includes a decorative icon glyph, so the match is not anchored).
  await fitView(page);
  const aiCard = page.locator(".react-flow__node").filter({ hasText: /\bAI\b|IA/ }).first();
  await dragNodeBy(page, aiCard, 170, 70);
  await fitView(page);

  // Start requires a non-empty input form before the server accepts a publish.
  await page.locator(".react-flow__node[data-id='start']").click();
  // Start fields use their name as the rendered label; no label-key field.
  await page.getByRole("button", { name: /^(add field|editor\.addField)$/i }).click();
  await page.getByLabel(/^(name|editor\.fieldName) 1$/i).fill("topic");
  await expect(page.getByLabel(/label key/i)).toHaveCount(0);

  // Connect Start→Script→AI→End on the canvas.
  const scriptId = await page
    .locator(".react-flow__node")
    .filter({ hasText: "Script" })
    .first()
    .getAttribute("data-id");
  const aiId = await aiCard.getAttribute("data-id");
  if (!scriptId || !aiId) throw new Error("Could not resolve generated node ids");
  await connectNodes(page, "start", scriptId);
  await connectNodes(page, scriptId, aiId);
  await connectNodes(page, aiId, "end");
  await expect(page.getByTestId("connection-count")).toHaveText(/3/);
}

// ─── AC-P2-04: launch a workflow from /tasks/new ───────────────────────────────

test("launch a task from /tasks/new and reach a terminal state", async ({ page, request }) => {
  test.setTimeout(900_000);
  await login(page);
  await page.goto("/tasks/new");

  // The seeded reference workflow is launchable and preselected.
  const workflowSelect = page.locator("#workflow");
  await expect(workflowSelect).toBeVisible({ timeout: 15_000 });
  await expect(page.locator("#workflow option:checked")).toHaveText(/reference-security-analysis/);

  // Start form fields are labelled by their declared name.
  const topicInput = page.getByLabel(/topic|tema/i);
  await expect(topicInput).toBeVisible();
  await topicInput.fill(`e2e-launch-${Date.now()}`);
  await page.getByRole("button", { name: /^add$|añadir$/i }).click();

  await expect(page).toHaveURL(/\/tasks\/[0-9a-f-]{36}$/, { timeout: 30_000 });
  const taskId = page.url().match(/\/tasks\/([0-9a-f-]{36})$/)?.[1];
  expect(taskId, "Task detail URL must carry the task id").toBeTruthy();

  const token = await apiToken(request);
  const task = await waitTerminalTask(request, token, taskId!);

  // The UI badge agrees with the API state.
  const terminalLabel: Record<string, RegExp> = {
    success: /succeeded|completada/i,
    failed: /failed|fallida/i,
    stopped: /stopped|detenida/i,
    waiting_for_input: /waiting|esperando|input|entrada|atención/i,
  };
  await expect(page.getByText(terminalLabel[task.state]).first()).toBeVisible({ timeout: 15_000 });

  if (task.state === "success") {
    // Artifacts the reference workflow declares (round-2 names).
    await expect(page.getByText(/\breport\b/).first()).toBeVisible();
    await expect(page.getByText(/\bdata\b/).first()).toBeVisible();
  } else if (task.state === "failed") {
    // Structured v2 provider-auth or runtime failure without any raw stack trace.
    await expect(
      page.getByText(/Add provider credentials before continuing|agent runtime failed|falló el entorno del agente/i).first(),
    ).toBeVisible();
    await expect(page.locator("body")).not.toContainText("Traceback (most recent call last)");
  }
});

// ─── AC-P2-04: author a workflow in the editor, publish, activate ──────────────

test("author a workflow (Start→Script→AI→End), save draft, publish, and activate", async ({ page, request }) => {
  test.setTimeout(300_000);
  await login(page, adminCredentials);

  const workflowName = `e2e-p2-authoring-${uniqueSuffix()}`;
  const workflowId = await createWorkflow(page, workflowName);
  await authorReferenceGraph(page, workflowName);

  // Save the draft: the header status flips to Saved.
  await saveDraft(page);

  // Publish: a version notice appears and names the created version.
  const publishResponsePromise = page.waitForResponse((response) =>
    response.url().includes("/publish") && response.request().method() === "POST",
  );
  await page.getByRole("button", { name: /^publish$|publicar$/i }).click();
  const publishResponse = await publishResponsePromise;
  expect(publishResponse.ok(), `Publish rejected: ${await publishResponse.text()}`).toBeTruthy();
  await expect(
    page.locator("[data-testid='editor-notice'][data-key='workflowEditor.publishSuccess']"),
  ).toHaveAttribute("data-version", "1", { timeout: 30_000 });

  // Activate through the explicit picker (publishing never activates).
  await page.getByRole("button", { name: /^activate$|activar$/i }).click();
  await expect(page.getByRole("heading", { name: /activate a version|activar una versión/i })).toBeVisible({
    timeout: 15_000,
  });
  await expect(page.getByLabel(/published version|versión publicada/i)).toContainText("Version 1");
  await page.getByRole("button", { name: /^confirm$|confirmar$/i }).click();
  await expect(
    page.locator("[data-testid='editor-notice'][data-key='workflowEditor.activateSuccess']"),
  ).toHaveAttribute("data-version", "1", { timeout: 30_000 });

  // The list page and the API both agree that version 1 is active.
  await page.goto("/workflows");
  const row = page.getByRole("listitem").filter({ hasText: workflowName });
  await expect(row.getByText(/version 1|versión 1/i)).toBeVisible({ timeout: 15_000 });
  const token = await apiToken(request, adminCredentials);
  const detail = await request.get(`/api/workflows/${workflowId}`, { headers: authed(token) });
  expect(detail.ok(), `GET workflow: ${await detail.text()}`).toBeTruthy();
  expect(((await detail.json()) as { active_version?: { version: number } }).active_version?.version).toBe(1);
});

// ─── AC-P2-06: publish must not auto-activate; the option must activate ────────

test("publishing does not change the active version unless 'Activate after publishing' is checked", async ({
  page,
}) => {
  test.setTimeout(300_000);
  await login(page, adminCredentials);

  const workflowName = `e2e-p2-publish-mode-${uniqueSuffix()}`;
  const workflowId = await createWorkflow(page, workflowName);
  await authorReferenceGraph(page, workflowName);
  await saveDraft(page);

  // The activate option is off by default (AC-P2-06).
  const activateOption = page.getByLabel(/activate after publishing|activar después de publicar/i);
  await expect(activateOption).not.toBeChecked();

  // Publish once with the option off: version 1 appears, nothing activates.
  const publishResponsePromise = page.waitForResponse((response) =>
    response.url().includes("/publish") && response.request().method() === "POST",
  );
  await page.getByRole("button", { name: /^publish$|publicar$/i }).click();
  const publishResponse = await publishResponsePromise;
  expect(publishResponse.ok(), `Publish rejected: ${await publishResponse.text()}`).toBeTruthy();
  await expect(
    page.locator("[data-testid='editor-notice'][data-key='workflowEditor.publishSuccess']"),
  ).toHaveAttribute("data-version", "1", { timeout: 30_000 });
  await expect(
    page.locator("[data-testid='editor-notice'][data-key='workflowEditor.activateSuccess']"),
  ).toHaveCount(0);

  // Reloaded list view: the workflow has no active version.
  await page.goto("/workflows");
  const row = page.getByRole("listitem").filter({ hasText: workflowName });
  await expect(row.getByText(/no active version|sin versión activa/i)).toBeVisible({ timeout: 15_000 });

  // Publish again with the option checked: version 2 is published AND active.
  await page.goto(`/workflows/${workflowId}/edit`);
  await expect(page.getByLabel(/activate after publishing|activar después de publicar/i)).toBeVisible({
    timeout: 15_000,
  });
  await page.getByLabel(/activate after publishing|activar después de publicar/i).check();
  await page.getByRole("button", { name: /^publish$|publicar$/i }).click();
  await expect(
    page.locator("[data-testid='editor-notice'][data-key='workflowEditor.publishSuccess']"),
  ).toHaveAttribute("data-version", "2", { timeout: 30_000 });
  await expect(
    page.locator("[data-testid='editor-notice'][data-key='workflowEditor.activateSuccess']"),
  ).toHaveAttribute("data-version", "2", { timeout: 30_000 });

  await page.goto("/workflows");
  await expect(
    page.getByRole("listitem").filter({ hasText: workflowName }).getByText(/version 2|versión 2/i),
  ).toBeVisible({ timeout: 15_000 });
});

// ─── AC-P2-01: provider row actions target the clicked row ─────────────────────

test("provider row actions: Test connection targets the clicked config; Delete asks for confirmation", async ({
  page,
  request,
}) => {
  test.setTimeout(180_000);
  const token = await apiToken(request);
  const suffix = uniqueSuffix();
  const configA = await createSyntheticProvider(request, token, `e2e-row-target-a-${suffix}`);
  const configB = await createSyntheticProvider(request, token, `e2e-row-target-b-${suffix}`);

  // Capture the verify requests instead of letting them run a real container
  // probe: the journey asserts UI wiring (which row id the dialog targets).
  const verifyRequests: { config_id?: string }[] = [];
  await page.route("**/api/providers/opencode/config/verify", async (route) => {
    verifyRequests.push(route.request().postDataJSON() as { config_id?: string });
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({ valid: true, violations: [], models: ["e2e-test-model"] }),
    });
  });

  try {
    await login(page);
    await page.goto("/providers");
    const rowA = page.getByRole("listitem").filter({ hasText: configA.name });
    const rowB = page.getByRole("listitem").filter({ hasText: configB.name });
    await expect(rowA).toBeVisible({ timeout: 15_000 });
    await expect(rowB).toBeVisible();

    // Row A's action must probe row A (assert on the request body).
    await rowA.getByRole("button", { name: /test connection|probar conexión/i }).click();
    await expect(page.getByRole("heading", { name: /test the connection|prueba la conexión/i })).toBeVisible({
      timeout: 15_000,
    });
    await expect(page.locator("#provider-verify-model")).toContainText("e2e-test-model");
    expect(verifyRequests.at(-1)?.config_id).toBe(configA.id);
    await page.getByRole("button", { name: /^close$|cerrar$/i }).click();
    await expect(page.getByRole("heading", { name: /test the connection|prueba la conexión/i })).toHaveCount(0);

    // Row B's action must probe row B, not the first row of the list.
    await rowB.getByRole("button", { name: /test connection|probar conexión/i }).click();
    await expect(page.getByRole("heading", { name: /test the connection|prueba la conexión/i })).toBeVisible({
      timeout: 15_000,
    });
    expect(verifyRequests.at(-1)?.config_id).toBe(configB.id);
    await page.getByRole("button", { name: /^close$|cerrar$/i }).click();

    // Delete asks for confirmation (styled dialog, not a native confirm):
    // the top-right close X keeps the row, confirming removes it and only it.
    const deleteButtonA = rowA.getByRole("button", { name: /^delete$|eliminar$/i });
    await deleteButtonA.click();
    const confirmDialog = page.getByRole("alertdialog");
    await expect(confirmDialog.getByText(/delete provider configuration|eliminar configuración del proveedor/i)).toBeVisible({
      timeout: 15_000,
    });
    await confirmDialog.getByRole("button", { name: /^close$|cerrar$/i }).click();
    await expect(rowA).toBeVisible();

    await deleteButtonA.click();
    await expect(confirmDialog.getByText(/delete provider configuration|eliminar configuración del proveedor/i)).toBeVisible({
      timeout: 15_000,
    });
    await confirmDialog.getByRole("button", { name: /^delete$|eliminar$/i }).click();
    await expect(rowA).toHaveCount(0, { timeout: 15_000 });
    await expect(rowB).toBeVisible();
  } finally {
    for (const row of [configA, configB]) await deleteProvider(request, token, row.id).catch(() => {});
  }
});

// ─── Credential-gated: a real model call through the row dialog ────────────────

test.describe("credential-gated journeys (documented prerequisite)", () => {
  test("Test connection performs a real model call against a real key", async ({ page, request }) => {
    // SKIPPED unless OPENCODE_API_KEY (or KOSMO_E2E_OPENCODE_API_KEY) is
    // exported.  The key exists only to build a throwaway provider row; the
    // test never prints it.  When present, a real verify-model call must
    // either verify with measured latency or surface a structured backend
    // error — an unstructured outcome fails this journey.
    test.skip(!providerKey, "Skipped: no provider credential configured (OPENCODE_API_KEY). " +
      "Export OPENCODE_API_KEY to run the real-model verification journey.");
    test.setTimeout(180_000);

    const token = await apiToken(request);
    const config = await createSyntheticProvider(request, token, `e2e-real-model-${uniqueSuffix()}`, {
      config: { provider: { opencode: { options: { apiKey: providerKey } } } },
      auth: { opencode: { type: "api", key: providerKey } },
    });
    try {
      await login(page);
      await page.goto("/providers");
      const row = page.getByRole("listitem").filter({ hasText: config.name });
      await expect(row).toBeVisible({ timeout: 15_000 });
      await row.getByRole("button", { name: /test connection|probar conexión/i }).click();
      await expect(page.getByRole("heading", { name: /test the connection|prueba la conexión/i })).toBeVisible({
        timeout: 30_000,
      });
      // Real discovery lists real models; pick the first and run the real call.
      const modelSelect = page.locator("#provider-verify-model");
      await expect(modelSelect).toBeVisible({ timeout: 60_000 });
      await page
        .getByRole("dialog")
        .getByRole("button", { name: /test connection|probar conexión/i })
        .click();
      const verified = page.getByText(/connection verified with|conexión verificada con/i);
      const structuredError = page.locator("[role='alert']");
      await expect(verified.or(structuredError.first()).first()).toBeVisible({ timeout: 120_000 });
      await expect(verified).toBeVisible({ timeout: 5_000 }).catch(async () => {
        throw new Error(
          `Real model verification did not succeed; last dialog state: ${await page
            .getByRole("dialog")
            .textContent()}`,
        );
      });
    } finally {
      await deleteProvider(request, token, config.id).catch(() => {});
    }
  });
});

// ─── AC-P2-10: English and Spanish paths for the new labels ────────────────────

test.describe("i18n – English and Spanish paths for the new labels", () => {
  /** Runs the shared label walk in the given language (as the admin: the
   *  workflow-creation step requires the builder/admin role). */
  async function walkCorePages(page: Page, labels: {
    signIn: RegExp; createTask: RegExp; workflows: RegExp; add: RegExp;
    editor: RegExp; saveDraft: RegExp; publish: RegExp; activate: RegExp;
    activateAfterPublish: RegExp; providers: RegExp;
    testConnection: RegExp; delete: RegExp;
  }): Promise<void> {
    await page.goto("/login");
    await expect(page.getByRole("heading", { name: labels.signIn })).toBeVisible();
    await login(page, adminCredentials);
    await expect(page.getByRole("heading", { name: labels.createTask })).toBeVisible();

    await page.goto("/workflows");
    await expect(page.getByRole("heading", { name: labels.workflows })).toBeVisible();
    await page.getByRole("button", { name: labels.add }).first().click();
    const nameInput = page.getByLabel(/^name$|nombre$/i);
    await expect(nameInput).toBeVisible({ timeout: 10_000 });
    await nameInput.fill(`e2e-p2-i18n-${uniqueSuffix()}`);
    await page.getByRole("button", { name: /create workflow|crear flujo de trabajo/i }).click();
    await page.waitForURL(/\/workflows\/[0-9a-f-]{36}\/edit/, { timeout: 30_000 });
    await expect(page.getByRole("heading", { name: labels.editor })).toBeVisible({ timeout: 15_000 });
    await expect(page.getByRole("button", { name: labels.saveDraft })).toBeVisible();
    await expect(page.getByRole("button", { name: labels.publish })).toBeVisible();
    await expect(page.getByRole("button", { name: labels.activate })).toBeVisible();
    await expect(page.getByLabel(labels.activateAfterPublish)).toBeVisible();
    // The palette (left aside) carries the per-type add buttons; the header
    // "Add node" button is mobile-only and hidden at the desktop viewport.
    await expect(page.getByRole("heading", { name: /node types|tipos de nodo/i })).toBeVisible();
    await expect(page.getByRole("button", { name: /^add script$|añadir script$/i })).toBeVisible();

    await page.goto("/providers");
    await expect(page.getByRole("heading", { name: labels.providers })).toBeVisible({ timeout: 15_000 });
    // Row actions exist on any visible row; create a throwaway row if the
    // list is empty so both actions are provably rendered.
    const anyRow = page.getByRole("listitem").filter({
      has: page.getByRole("button", { name: labels.testConnection }),
    });
    if ((await anyRow.count()) === 0) {
      const token = await apiToken(page.request, adminCredentials);
      const created = await createSyntheticProvider(page.request, token, `e2e-i18n-row-${uniqueSuffix()}`);
      await page.reload({ waitUntil: "networkidle" });
      await expect(page.getByRole("listitem").filter({ hasText: created.name })).toBeVisible({ timeout: 15_000 });
      await expect(
        page.getByRole("listitem").filter({ hasText: created.name })
          .getByRole("button", { name: labels.delete }),
      ).toBeVisible();
      await deleteProvider(page.request, token, created.id);
    } else {
      await expect(anyRow.first()).toBeVisible();
    }
  }

  test("English labels render on the new phase-2 surfaces", async ({ page }) => {
    await page.addInitScript(() => window.localStorage.setItem("kosmo.language", "en"));
    await walkCorePages(page, {
      signIn: /^Sign in$/,
      createTask: /^Create a task$/,
      workflows: /^Workflows$/,
      add: /^Add$/,
      editor: /^Workflow editor$/,
      saveDraft: /^Save draft$/,
      publish: /^Publish$/,
      activate: /^Activate$/,
      activateAfterPublish: /Activate after publishing/,
      providers: /^Providers$/,
      testConnection: /^Test connection$/,
      delete: /^Delete$/,
    });
  });

  test("Spanish labels render on the new phase-2 surfaces via the language switcher", async ({ page }) => {
    await page.goto("/login");
    await page.getByRole("button", { name: /^Español$/ }).click();
    await expect(page.getByRole("heading", { name: /^Iniciar sesión$/ })).toBeVisible();
    await walkCorePages(page, {
      signIn: /^Iniciar sesión$/,
      createTask: /^Crear una tarea$/,
      workflows: /^Flujos de trabajo$/,
      add: /^Añadir$/,
      editor: /^Editor de flujos de trabajo$/,
      saveDraft: /^Guardar borrador$/,
      publish: /^Publicar$/,
      activate: /^Activar$/,
      activateAfterPublish: /Activar después de publicar/,
      providers: /^Proveedores$/,
      testConnection: /^Probar conexión$/,
      delete: /^Eliminar$/,
    });
  });
});

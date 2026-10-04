// Phase-2 acceptance journey for AC-P2-08: a visually authored
// Start→Script→AI→End graph is published, activated, launched from
// /tasks/new, and executes end-to-end to `success` with its declared
// artifacts.  This is the journey the architect flagged as missing (RR8):
// authoring alone does not prove execution.
//
// Prerequisite (credential-gated): the launching account must own (or see) a
// verified OpenCode provider configuration whose model can answer, because the
// AI node resolves its runtime config from the task creator.  The seeded
// `admin` account owns the verified provider in the local compose stack; the
// model is configurable via KOSMO_E2E_OPENCODE_MODEL (default nan/qwen3.6, the
// model verified live in this environment).  If no verified provider is
// visible the journey is reported as SKIPPED with a reason — never as passing.
//
// Run against a running compose stack:
//   pnpm -C frontend exec playwright test e2e/phase2-execution.e2e.ts

import { expect, test, type APIRequestContext, type Page } from "@playwright/test";

const adminUsername = process.env.KOSMO_E2E_ADMIN_USERNAME ?? "admin";
const adminPassword = process.env.KOSMO_E2E_ADMIN_PASSWORD ?? "admin-change-me";

function uniqueSuffix(): string {
  return `${Date.now()}-${Math.random().toString(36).slice(2, 8)}`;
}

async function apiToken(request: APIRequestContext): Promise<string> {
  const response = await request.post("/api/auth/login", {
    data: { username: adminUsername, password: adminPassword },
  });
  if (!response.ok()) throw new Error(`API login failed: ${response.status()} ${await response.text()}`);
  return (await response.json()).access_token as string;
}

function authed(token: string): Record<string, string> {
  return { Authorization: `Bearer ${token}` };
}

const TERMINAL_TASK_STATES = ["success", "failed", "stopped"];

async function waitTerminalTask(
  request: APIRequestContext,
  token: string,
  taskId: string,
  timeoutMs = 600_000,
): Promise<{ state: string }> {
  const deadline = Date.now() + timeoutMs;
  let lastState = "unknown";
  while (Date.now() < deadline) {
    const response = await request.get(`/api/tasks/${taskId}`, { headers: authed(token) });
    if (response.ok()) {
      const payload = (await response.json()) as { task?: { state: string } } & { state?: string };
      const task = payload.task ?? payload;
      lastState = task.state;
      if (TERMINAL_TASK_STATES.includes(lastState)) return { state: lastState };
    }
    await new Promise((resolve) => setTimeout(resolve, 2_000));
  }
  throw new Error(`Task ${taskId} did not reach a terminal state within ${timeoutMs}ms (last state: ${lastState})`);
}

async function login(page: Page): Promise<void> {
  await page.goto("/login");
  await expect(page.getByRole("heading", { name: /sign in|iniciar sesión/i })).toBeVisible({ timeout: 15_000 });
  await page.getByLabel(/username|usuario/i).fill(adminUsername);
  await page.getByLabel(/password|contraseñ?a/i).fill(adminPassword);
  await page.getByRole("button", { name: /sign in|iniciar sesión/i }).click();
  await expect(page).toHaveURL(/\/tasks/, { timeout: 15_000 });
}

/** Reads the required "topic" input value off the Start input form. */
async function createWorkflow(page: Page, name: string): Promise<string> {
  await page.goto("/workflows");
  await expect(page.getByRole("heading", { name: /workflows|flujos de trabajo/i })).toBeVisible({ timeout: 15_000 });
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

async function fillScriptCode(page: Page, code: string): Promise<void> {
  // The journey needs deterministic code entry: typing into Monaco triggers
  // its suggestion widget, which drops spaces and corrupts Python.  Blocking
  // the lazy chunk makes the modal render its plain-text fallback textarea
  // (a supported path), which fill() sets verbatim.  Monaco lazy-loading is
  // covered by its own unit tests.
  await page.route("**/*monaco*", (route) => route.abort());
  try {
    await page.getByRole("button", { name: /edit script|editar script/i }).click();
    const dialog = page.getByRole("dialog");
    await expect(dialog).toBeVisible({ timeout: 15_000 });
    const textarea = dialog.getByLabel(/^code$|código$/i);
    await expect(textarea).toBeVisible({ timeout: 20_000 });
    await textarea.fill(code);
    await dialog.getByRole("button", { name: /^save$|guardar$/i }).click();
    await expect(dialog).not.toBeVisible({ timeout: 15_000 });
  } finally {
    await page.unroute("**/*monaco*");
  }
}

async function connectNodes(page: Page, source: string, target: string): Promise<void> {
  const sourceHandle = page.locator(`.react-flow__node[data-id="${source}"] .react-flow__handle.source`);
  const targetHandle = page.locator(`.react-flow__node[data-id="${target}"] .react-flow__handle.target`);
  await sourceHandle.hover();
  await page.mouse.down();
  await targetHandle.hover();
  await page.mouse.up();
}

async function dragNodeBy(page: Page, node: ReturnType<Page["locator"]>, dx: number, dy: number): Promise<void> {
  const box = await node.boundingBox();
  if (!box) throw new Error("Node bounding box unavailable");
  await node.hover();
  await page.mouse.down();
  await page.mouse.move(box.x + box.width / 2 + dx, box.y + box.height / 2 + dy, { steps: 8 });
  await page.mouse.up();
}

async function saveDraft(page: Page): Promise<void> {
  await page.getByRole("button", { name: /^save draft$|^guardar borrador$/i }).click();
  await expect(page.locator("header [role='status']")).toHaveText(/^(Saved|Guardado)$/, { timeout: 30_000 });
}

async function fitView(page: Page): Promise<void> {
  await page.getByRole("button", { name: "Fit view", exact: true }).click();
  await page.waitForTimeout(400);
}

/** The destructive reset replaced inline agents with a seeded global reference. */
async function chooseReferenceAgent(page: Page): Promise<void> {
  const selector = page.getByRole("combobox", { name: /agent|agente/i });
  await expect(selector).toBeVisible();
  await selector.fill("reference-security-analysis-agent");
  await page.getByRole("option", { name: "reference-security-analysis-agent" }).click();
}

/**
 * Waits for the authored task while answering any legitimate agent input
 * request through the task detail form (never a global auto-approval). Returns
 * the last observed state; the caller asserts success explicitly.
 */
async function waitForSuccessAnsweringInput(
  page: Page,
  request: APIRequestContext,
  token: string,
  taskId: string,
  timeoutMs = 720_000,
): Promise<string> {
  const deadline = Date.now() + timeoutMs;
  let lastState = "unknown";
  while (Date.now() < deadline) {
    const response = await request.get(`/api/tasks/${taskId}`, { headers: authed(token) });
    if (response.ok()) {
      const payload = (await response.json()) as { task?: { state: string } } & { state?: string };
      const task = payload.task ?? payload;
      lastState = task.state;
      if (["success", "failed", "stopped"].includes(lastState)) return lastState;
      if (lastState === "waiting_for_input") {
        const answer = page.locator("#task-answer");
        if (await answer.isVisible().catch(() => false)) {
          await answer.fill("yes").catch(() => {});
          await page
            .getByRole("button", { name: /send answer|enviar respuesta/i })
            .click()
            .catch(() => {});
        }
      }
    }
    await new Promise((resolve) => setTimeout(resolve, 2_000));
  }
  return lastState;
}

/**
 * Authors Start→Script→AI→End through the real editor UI.  The AI node runs
 * the configured real model and must produce summary; the script produces
 * report and data from its declared return.
 */
async function authorExecutableGraph(page: Page): Promise<void> {
  const scriptCode = "report = f'# Security analysis\\n\\nTopic: {topic}\\n\\nA short report about security.'\ndata = {'topic': topic, 'findings': []}\nreturn report, data";

  // Add Script (selected on add) and commit its code.
  await page.getByRole("button", { name: /^add script$|añadir script$/i }).click();
  await fillScriptCode(page, scriptCode);

  // AI nodes use a catalog reference. Instructions are agent-owned, not inline.
  await page.getByRole("button", { name: /^add ai$|añadir ia$/i }).click();
  await chooseReferenceAgent(page);
  await fitView(page);
  const aiCard = page.locator(".react-flow__node").filter({ hasText: /\bAI\b|IA/ }).first();
  await dragNodeBy(page, aiCard, 170, 70);
  await fitView(page);
  await page.getByLabel(/prompt template|plantilla de prompt/i).fill(
    "Read report and write a concise summary to summary. Start with a top-level heading exactly \"Summary\" and include the word security.",
  );

  // AI output artifacts remain explicitly declared; inputs are derived when
  // the script edge is connected below.
  await page.getByRole("button", { name: /^add output$|^añadir salida$/i }).click();
  await page.getByLabel(/^outputs 1$/i).fill("summary");
  await page.getByRole("button", { name: /validation.*summary/i }).click();
  const validationDialog = page.getByRole("dialog");
  await validationDialog.getByLabel(/format/i).selectOption("markdown");
  // Markdown is parse-only in the round-2 contract: no schema and no rules.
  await validationDialog.getByRole("button", { name: /save|guardar/i }).click();
  await expect(validationDialog).not.toBeVisible();

  // Start: one required string input named topic.
  await page.locator(".react-flow__node[data-id='start']").click();
  await page.getByRole("button", { name: /^add field$|añadir campo$/i }).click();
  await page.getByLabel(/^(name|nombre) 1$/i).fill("topic");

  // Script input and outputs are derived from Start edge and return names.
  await fitView(page);
  const scriptNode = page.locator(".react-flow__node").filter({ hasText: "Script" }).first();
  // Connect Start→Script→AI→End.
  const scriptId = await scriptNode.getAttribute("data-id");
  const aiId = await aiCard.getAttribute("data-id");
  if (!scriptId || !aiId) throw new Error("Could not resolve generated node ids");
  await connectNodes(page, "start", scriptId);
  await connectNodes(page, scriptId, aiId);
  await connectNodes(page, aiId, "end");
  await expect(page.getByTestId("connection-count")).toHaveText(/3/, { timeout: 10_000 });
  await scriptNode.click();
  await expect(page.getByText("topic", { exact: true })).toBeVisible();
  await expect(page.getByText("report", { exact: true })).toBeVisible();
  await expect(page.getByText("data", { exact: true })).toBeVisible();
}

test("executes a visually authored Start→Script→AI→End graph to success", async ({ page, request }) => {
  test.setTimeout(900_000);

  const token = await apiToken(request);

  // Credential gate: a verified provider visible to the launching account is
  // required for the AI node to answer.  Report SKIPPED, never a false pass.
  const configs = await request.get("/api/providers/opencode/config", { headers: authed(token) });
  const verified = configs.ok()
    ? ((await configs.json()) as { verification_status?: string }[]).some((row) => row.verification_status === "verified")
    : false;
  if (!verified) test.skip(true, "No verified OpenCode provider configuration is visible; AI success cannot be established.");

  await login(page);

  const workflowName = `e2e-exec-${uniqueSuffix()}`;
  const workflowId = await createWorkflow(page, workflowName);
  await authorExecutableGraph(page);

  // Save → publish (version 1) → activate (explicit picker, default preselection).
  await saveDraft(page);
  await page.getByRole("button", { name: /^publish$|publicar$/i }).click();
  await expect(
    page.locator("[data-testid='editor-notice'][data-key='workflowEditor.publishSuccess']"),
  ).toHaveAttribute("data-version", "1", { timeout: 30_000 });
  await page.getByRole("button", { name: /^activate$|activar$/i }).click();
  await expect(page.getByRole("heading", { name: /activate a version|activar una versión/i })).toBeVisible({ timeout: 15_000 });
  await page.getByRole("button", { name: /^confirm$|confirmar$/i }).click();
  await expect(
    page.locator("[data-testid='editor-notice'][data-key='workflowEditor.activateSuccess']"),
  ).toHaveAttribute("data-version", "1", { timeout: 30_000 });

  // Launch the authored workflow from /tasks/new through the real UI.
  await page.goto("/tasks/new");
  await expect(page.locator("#workflow")).toBeVisible({ timeout: 15_000 });
  await page.locator("#workflow").selectOption(workflowId);
  const topicInput = page.locator("#task-input-topic");
  await expect(topicInput).toBeVisible({ timeout: 10_000 });
  await topicInput.fill("security");
  await page.getByRole("button", { name: /^add$|añadir$/i }).click();
  await page.waitForURL(/\/tasks\/[0-9a-f-]{36}$/, { timeout: 60_000 });
  const taskId = page.url().match(/\/tasks\/([0-9a-f-]{36})$/)?.[1];
  expect(taskId, "Task detail URL must carry the task id").toBeTruthy();

  // Follow to success while answering any legitimate agent input request.
  const state = await waitForSuccessAnsweringInput(page, request, token, taskId!);
  expect(state, "Authored graph must reach success").toBe("success");

  await expect(page.getByText(/succeeded|completada/i).first()).toBeVisible({ timeout: 15_000 });
  await expect(page.getByText(/summary/).first()).toBeVisible({ timeout: 15_000 });
  await expect(page.getByText(/report/).first()).toBeVisible({ timeout: 15_000 });
  await expect(page.locator("body")).not.toContainText("Traceback (most recent call last)");
});

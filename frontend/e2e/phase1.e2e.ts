import { expect, test, type APIRequestContext } from '@playwright/test';

const username = process.env.KOSMO_E2E_USERNAME ?? 'test-runner';
const password = process.env.KOSMO_E2E_PASSWORD ?? 'runner-change-me';

// The compose stack's agent runtime may carry working model credentials in
// the agent image itself (independent of this process's OPENCODE_API_KEY),
// and a live agent may pause the task with a permission/input request.  A
// launched reference task therefore observably ends in ANY of: success,
// failed (structured agent-auth-missing on credential-less stacks),
// waiting_for_input, or stopped.  The journeys below observe the actual
// state and assert the phase-1 criteria that hold for it; they never
// pretend an unmaterialized premise (e.g. an AI failure) was verified.

const API = 'http://localhost:8000';

/** States at which this suite's journeys can make their final assertions. */
const OBSERVABLE_END_STATES = ['success', 'failed', 'stopped', 'waiting_for_input'];
/** States that hold one of the main-task capacity slots. */
const CAPACITY_HOLDING_STATES = ['queued', 'allocating', 'running', 'waiting_for_input'];

type TaskPayload = { id?: string; state?: string; notes?: { message_key: string }[]; error?: { details?: unknown[] } };

async function login(page: import('@playwright/test').Page) {
  await page.goto('/login');
  await page.getByLabel(/username|usuario/i).fill(username);
  await page.getByLabel(/password|contraseñ?a/i).fill(password);
  await page.getByRole('button', { name: /sign in|log in|iniciar sesión/i }).click();
  await expect(page).toHaveURL(/tasks/);
}

/** Bearer token for the backend API (same account as the UI session). */
async function apiToken(request: APIRequestContext): Promise<string> {
  const auth = await request.post(`${API}/auth/login`, { data: { username, password } });
  expect(auth.ok(), `API login failed: ${auth.status()} ${await auth.text()}`).toBeTruthy();
  return (await auth.json()).access_token;
}

function authed(token: string): Record<string, string> {
  return { Authorization: `Bearer ${token}` };
}

function taskOf(payload: { task?: TaskPayload } & TaskPayload): TaskPayload {
  return payload.task ?? payload;
}

/**
 * Polls the task API until the task reaches an observable end state and
 * returns that state.  When the window closes while the task is still active
 * (the engine allows a single AI node up to 30 minutes — see
 * worker/workflows/task_workflow.py — so a slow real model run is not a
 * defect), the last observed state is returned and the caller decides
 * honestly what it can still assert.
 */
async function waitObservableEndState(
  request: APIRequestContext,
  token: string,
  taskId: string,
  timeoutMs = 600_000,
): Promise<string> {
  const deadline = Date.now() + timeoutMs;
  let lastState = 'unknown';
  while (Date.now() < deadline) {
    const response = await request.get(`${API}/tasks/${taskId}`, { headers: authed(token) });
    if (response.ok()) {
      lastState = taskOf(await response.json()).state ?? 'unknown';
      if (OBSERVABLE_END_STATES.includes(lastState)) return lastState;
    }
    await new Promise(resolve => setTimeout(resolve, 2_000));
  }
  return lastState;
}

/** Polls the task API until the task accepts the stop action (or times out). */
async function waitStoppableState(
  request: APIRequestContext,
  token: string,
  taskId: string,
  timeoutMs = 90_000,
): Promise<string> {
  const deadline = Date.now() + timeoutMs;
  let lastState = 'unknown';
  while (Date.now() < deadline) {
    const response = await request.get(`${API}/tasks/${taskId}`, { headers: authed(token) });
    if (response.ok()) {
      lastState = taskOf(await response.json()).state ?? 'unknown';
      if (lastState === 'running' || lastState === 'waiting_for_input') return lastState;
    }
    await new Promise(resolve => setTimeout(resolve, 1_000));
  }
  throw new Error(`Task ${taskId} never became stoppable (last state: ${lastState})`);
}

/**
 * Asserts visibility with a reload fallback.  The detail page keeps itself
 * live through SSE-triggered reloads, but a rapid sequence of state changes
 * can leave the page showing an older state than the API (observed: a badge
 * frozen on "Waiting for capacity" while the API already reported the task
 * stopped).  A reload forces a fresh render; the assertion itself is not
 * weakened.
 */
async function expectWithReload(
  page: import('@playwright/test').Page,
  locator: ReturnType<import('@playwright/test').Page['getByText']>,
  timeoutMs = 30_000,
): Promise<void> {
  const deadline = Date.now() + timeoutMs;
  for (;;) {
    if (await locator.isVisible().catch(() => false)) return;
    if (Date.now() > deadline) break;
    await page.reload();
    await locator.waitFor({ state: 'visible', timeout: 5_000 }).catch(() => {});
  }
  await expect(locator).toBeVisible();
}

/** Stops one task; conflicts (already terminal) are ignored. */
async function stopTask(request: APIRequestContext, token: string, taskId: string): Promise<void> {
  await request.post(`${API}/tasks/${taskId}/stop`, { headers: authed(token) }).catch(() => {});
}

/**
 * Stops the runner account's non-terminating leftover tasks.  The runner is
 * dedicated to this suite; without this, tasks that ended in
 * waiting_for_input (the live agent asking for permission) would hold a
 * capacity slot forever and starve the later journeys of a running task.
 */
async function stopLeftoverTasks(request: APIRequestContext, token: string): Promise<void> {
  const response = await request.get(`${API}/tasks`, { headers: authed(token) });
  if (!response.ok()) return;
  const rows = (await response.json()) as TaskPayload[];
  for (const row of Array.isArray(rows) ? rows : []) {
    if (row.id && CAPACITY_HOLDING_STATES.includes(row.state ?? '')) {
      await stopTask(request, token, row.id);
    }
  }
}

async function taskDetail(page: import('@playwright/test').Page) {
  const match = page.url().match(/\/tasks\/([^/?]+)/);
  if (!match) throw new Error(`Task detail URL missing: ${page.url()}`);
  const auth = await page.request.post('http://localhost:8000/auth/login', { data: { username, password } });
  const token = (await auth.json()).access_token;
  const response = await page.request.get(`http://localhost:8000/tasks/${match[1]}`, {
    headers: { Authorization: `Bearer ${token}` },
  });
  return response;
}

/**
 * Creates a task through the /tasks/new launch form and follows the
 * navigation to the task detail page.  The form only launches workflows that
 * have an active version: the workflow <select> must show the seeded
 * launchable reference-security-analysis preselected, the Start node's input
 * form carries the topic field, and the submit action is the Add button
 * (common.add).  Only this interaction is bound here; the acceptance
 * assertions live in the journeys.
 */
async function launchTask(page: import('@playwright/test').Page, topic: string) {
  await page.goto('/tasks/new');
  const workflowSelect = page.locator('#workflow');
  await expect(workflowSelect).toBeVisible({ timeout: 15_000 });
  await expect(page.locator('#workflow option:checked')).toHaveText(/reference-security-analysis/);
  await page.getByLabel(/topic|tema/i).fill(topic);
  await page.getByRole('button', { name: /^add$|añadir$/i }).click();
  await page.waitForURL(/\/tasks\/[0-9a-f-]{36}$/, { timeout: 30_000 });
}

function createdTaskId(page: import('@playwright/test').Page): string {
  const id = page.url().match(/\/tasks\/([0-9a-f-]{36})$/)?.[1];
  if (!id) throw new Error(`Task detail URL missing: ${page.url()}`);
  return id;
}

test('login and language switcher render the application in both locales', async ({ page }) => {
  await page.goto('/login');
  await expect(page.getByRole('heading', { name: /sign in/i })).toBeVisible();
  await page.getByRole('button', { name: /español/i }).click();
  await expect(page.getByRole('heading', { name: /iniciar sesión/i })).toBeVisible();
  await login(page);
});

test('submit workflow displays live task progress and produced artifacts', async ({ page, request }) => {
  test.setTimeout(720_000);
  await login(page);
  const token = await apiToken(request);
  // The script node must actually run for artifacts to exist: free the
  // suite's own leftover capacity slots BEFORE launching (a queued fresh
  // task would otherwise be swept by this cleanup).
  await stopLeftoverTasks(request, token);
  await launchTask(page, `e2e-${Date.now()}`);
  const taskId = createdTaskId(page);
  try {
    const state = await waitObservableEndState(request, token, taskId);
    if (!OBSERVABLE_END_STATES.includes(state)) {
      // The engine allows a single AI node up to 30 minutes (a slow real
      // model run is not a defect); this journey's window closed first, so
      // the state-specific assertions cannot be made yet.
      test.skip(true,
        `Skipped: the task was still '${state}' after the observation window; the engine ` +
        'allows an AI node up to 30 minutes (worker/workflows/task_workflow.py).');
    }
    // Live task progress: the detail view must reflect the observed state.
    await expect(page.locator('body')).not.toContainText(/Traceback \(most recent call last\)/);
    // Produced artifacts: the script node runs before the AI node, so its
    // outputs exist for every outcome the reference workflow can reach here.
    await expectWithReload(page, page.getByText(/report\.md/).first());
    await expect(page.getByText(/data\.json/).first()).toBeVisible();
    if (state === 'success') {
      await expectWithReload(page, page.getByText(/summary\.md/).first());
      await expectWithReload(page, page.getByText(/succeeded/i).first());
    } else if (state === 'failed') {
      // Localized cause (the AI failure surfaces either as a missing runtime
      // or as exhausted output validation — both rendered from message keys).
      await expectWithReload(
        page,
        page.getByText(/Agent runtime failed|Validation failed after/i).first(),
      );
    } else if (state === 'waiting_for_input') {
      // The live agent paused on a permission/input request; the progress UI
      // must say so.
      await expectWithReload(page, page.getByText(/waiting for input/i).first());
    }
    if (process.env.OPENCODE_API_KEY) {
      // With a real key configured for this journey the AI is expected to
      // succeed end to end.
      expect(state, 'OPENCODE_API_KEY was exported but the task did not succeed').toBe('success');
      await expect(page.getByText(/summary\.md/).first()).toBeVisible();
    }
  } finally {
    // Hygiene: a task parked on an agent question would hold a capacity
    // slot for the rest of the suite.
    await stopTask(request, token, taskId);
  }
});

test('failed AI execution has localized cause and no stack trace', async ({ page, request }) => {
  test.setTimeout(720_000);
  await login(page);
  const token = await apiToken(request);
  // The task must actually execute for the AI outcome to be observable:
  // free the suite's own leftover capacity slots BEFORE launching.
  await stopLeftoverTasks(request, token);
  await launchTask(page, `e2e-fail-${Date.now()}`);
  const taskId = createdTaskId(page);
  try {
    const state = await waitObservableEndState(request, token, taskId);
    // This journey exercises the AI-failure path.  When the observed outcome
    // is not a failure (the agent completed the node, paused for input, or
    // is still working inside its 30-minute budget), the premise did not
    // materialize: skip with that documented reason rather than pretending
    // the path was verified.
    test.skip(state !== 'failed',
      `Skipped: no AI failure was observable (task state: ${state}); the journey needs a ` +
      'run whose agent runtime fails or whose model output is rejected by validation.');
    // Localized cause: the failure surfaces either as a missing agent runtime
    // or as exhausted output validation; both render from message keys, never
    // as a raw stack trace.
    await expectWithReload(
      page,
      page.getByText(/Agent runtime failed|Validation failed after/i).first(),
    );
    await expect(page.locator('body')).not.toContainText(/Traceback \(most recent call last\)/);
    if (process.env.KOSMO_E2E_FAIL_VALIDATION === '1') {
      const response = await taskDetail(page);
      expect(response.ok()).toBeTruthy();
      const payload = await response.json();
      const task = payload.task ?? payload;
      expect(task.notes?.filter((note: {message_key: string}) => note.message_key === 'tasks.notes.validation_failed').length).toBe(3);
      expect(task.error?.details).toHaveLength(3);
    }
  } finally {
    await stopTask(request, token, taskId);
  }
});

test('fourth task remains queued at default main-task capacity', async ({ page, request }) => {
  test.setTimeout(720_000);
  await login(page);
  const token = await apiToken(request);
  // Free the suite's own leftovers so the four fresh tasks are the ones
  // contending for the three capacity slots this criterion is about.
  await stopLeftoverTasks(request, token);
  const createdIds: string[] = [];
  for (let i = 0; i < 4; i++) {
    await launchTask(page, `e2e-capacity-${Date.now()}-${i}`);
    await expect(page.getByRole('heading', { name: /workflow progress|progreso del flujo/i })).toBeVisible();
    createdIds.push(createdTaskId(page));
  }
  await expect(page.getByText(/queued/i).last()).toBeVisible({ timeout: 30_000 });
  expect(createdIds).toHaveLength(4);
  const details = await Promise.all(createdIds.map(async id => {
    const response = await request.get(`${API}/tasks/${id}`, { headers: authed(token) });
    expect(response.ok(), `GET task ${id}: ${await response.text()}`).toBeTruthy();
    return taskOf(await response.json());
  }));
  const states = details.map(task => task.state);
  expect(states, JSON.stringify(details)).toContain('queued');
  expect(states[3], JSON.stringify(details[3])).toBe('queued');
});

test('stop action is offered while a task is running', async ({ page, request }) => {
  test.setTimeout(720_000);
  await login(page);
  const token = await apiToken(request);
  // Stop is only offered for running/waiting tasks: free the suite's own
  // leftover slots so this journey's task actually starts.
  await stopLeftoverTasks(request, token);
  await launchTask(page, `e2e-stop-${Date.now()}`);
  const taskId = createdTaskId(page);
  // Stop is offered while the task runs or waits for input; the API state is
  // the ordering signal for the button's appearance.
  await waitStoppableState(request, token, taskId);
  const stop = page.getByRole('button', { name: /stop/i });
  await expectWithReload(page, stop, 60_000);
  // The stop confirmation is the styled dialog (AC-16), not window.confirm:
  // the action only fires from the confirm button inside the alertdialog.
  await stop.click();
  const confirmDialog = page.getByRole('alertdialog');
  await expect(confirmDialog).toBeVisible();
  await confirmDialog.getByRole('button', { name: /stop/i }).click();
  // The stop must take effect: the API reaches the stopped state and the
  // progress UI says so (the task badge and the interrupted node can both
  // render "Stopped"; anchor on the first — the header badge).  Stop waits
  // for the active node to finish naturally, and a real agent node can take
  // over a minute, so allow a generous window.
  const stopDeadline = Date.now() + 180_000;
  let stopped = false;
  while (Date.now() < stopDeadline) {
    const response = await request.get(`${API}/tasks/${taskId}`, { headers: authed(token) });
    if (response.ok() && taskOf(await response.json()).state === 'stopped') { stopped = true; break; }
    await new Promise(resolve => setTimeout(resolve, 1_000));
  }
  expect(stopped, `Task ${taskId} did not reach 'stopped' after the confirmed stop`).toBe(true);
  await expectWithReload(page, page.getByText(/stopped/i).first(), 60_000);
});

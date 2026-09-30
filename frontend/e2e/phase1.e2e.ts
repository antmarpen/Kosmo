import { expect, test } from '@playwright/test';

const username = process.env.KOSMO_E2E_USERNAME ?? 'test-runner';
const password = process.env.KOSMO_E2E_PASSWORD ?? 'runner-change-me';

async function login(page: import('@playwright/test').Page) {
  await page.goto('/login');
  await page.getByLabel(/username|usuario/i).fill(username);
  await page.getByLabel(/password|contraseñ?a/i).fill(password);
  await page.getByRole('button', { name: /sign in|log in|iniciar sesión/i }).click();
  await expect(page).toHaveURL(/tasks/);
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

test('login and language switcher render the application in both locales', async ({ page }) => {
  await page.goto('/login');
  await expect(page.getByRole('heading', { name: /sign in/i })).toBeVisible();
  await page.getByRole('button', { name: /español/i }).click();
  await expect(page.getByRole('heading', { name: /iniciar sesión/i })).toBeVisible();
  await login(page);
});

test('submit workflow displays live task progress and produced artifacts', async ({ page }) => {
  test.setTimeout(180_000);
  await login(page);
  await page.goto('/tasks/new');
  await page.getByLabel(/topic/i).fill(`e2e-${Date.now()}`);
  await page.getByRole('button', { name: /create task|submit/i }).click();
  await expect(page.getByText(/reference-security-analysis/)).toBeVisible();
  await expect(page.getByText(/report\.md/)).toBeVisible({ timeout: 120_000 });
  await expect(page.getByText(/data\.json/)).toBeVisible();
  // The detail view is the behavioral assertion surface; AI is only expected
  // to succeed when real OpenCode credentials are configured.
  if (process.env.OPENCODE_API_KEY) {
    await expect(page.getByText(/summary\.md/)).toBeVisible({ timeout: 120_000 });
    await expect(page.getByText(/success/i).last()).toBeVisible();
  } else {
    await expect(page.getByText(/Agent runtime failed/i)).toBeVisible({ timeout: 120_000 });
    await expect(page.locator('body')).not.toContainText(/Traceback \(most recent call last\)/);
  }
});

test('failed AI execution has localized cause and no stack trace', async ({ page }) => {
  test.setTimeout(180_000);
  await login(page);
  await page.goto('/tasks/new');
  await page.getByLabel(/topic/i).fill(`e2e-fail-${Date.now()}`);
  await page.getByRole('button', { name: /create task|submit/i }).click();
  await expect(page.getByText(/Agent runtime failed/i)).toBeVisible({ timeout: 120_000 });
  await expect(page.locator('body')).not.toContainText(/Traceback \(most recent call last\)/);
  if (process.env.KOSMO_E2E_FAIL_VALIDATION === '1') {
    const response = await taskDetail(page);
    expect(response.ok()).toBeTruthy();
    const payload = await response.json();
    const task = payload.task ?? payload;
    expect(task.notes?.filter((note: {message_key: string}) => note.message_key === 'tasks.notes.validation_failed').length).toBe(3);
    expect(task.error?.details).toHaveLength(3);
  }
});

test('fourth task remains queued at default main-task capacity', async ({ page }) => {
  test.setTimeout(180_000);
  await login(page);
  const createdIds: string[] = [];
  for (let i = 0; i < 4; i++) {
    await page.goto('/tasks/new');
    await page.getByLabel(/topic/i).fill(`e2e-capacity-${Date.now()}-${i}`);
    await page.getByRole('button', { name: /create task|submit/i }).click();
    await page.waitForURL(/\/tasks\/[0-9a-f-]{36}$/);
    await expect(page.getByRole('heading', { name: /workflow progress|progreso del flujo/i })).toBeVisible();
    const id = page.url().match(/\/tasks\/([^/?]+)/)?.[1];
    if (id) createdIds.push(id);
  }
  await expect(page.getByText(/queued/i).last()).toBeVisible({ timeout: 30_000 });
  expect(createdIds).toHaveLength(4);
  const auth = await page.request.post('http://localhost:8000/auth/login', { data: { username, password } });
  const token = (await auth.json()).access_token;
  const details = await Promise.all(createdIds.map(async id => {
    const response = await page.request.get(`http://localhost:8000/tasks/${id}`, { headers: { Authorization: `Bearer ${token}` } });
    expect(response.ok(), `GET task ${id}: ${await response.text()}`).toBeTruthy();
    const payload = await response.json();
    return payload.task ?? payload.data?.task ?? payload.data ?? payload;
  }));
  const states = details.map(task => task.state);
  expect(states, JSON.stringify(details)).toContain('queued');
  expect(states[3], JSON.stringify(details[3])).toBe('queued');
});

test('stop action is offered while a task is running', async ({ page }) => {
  test.setTimeout(180_000);
  await login(page);
  await page.goto('/tasks/new');
  await page.getByLabel(/topic/i).fill(`e2e-stop-${Date.now()}`);
  await page.getByRole('button', { name: /create task|submit/i }).click();
  const stop = page.getByRole('button', { name: /stop/i });
  await expect(stop).toBeVisible({ timeout: 60_000 });
  page.once('dialog', dialog => dialog.accept());
  await stop.click();
  await expect(page.getByText(/stopped/i)).toBeVisible({ timeout: 60_000 });
});

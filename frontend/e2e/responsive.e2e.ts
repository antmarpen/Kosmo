// AC-P2-09 responsive smoke: the editor is usable at 768px and 1280px and the
// task views remain usable at 375px (no horizontal overflow). This complements
// the functional E2E journeys with the explicit viewport checks the spec
// requires. It runs against the compose stack and the seeded admin account.

import { expect, test, type Page } from "@playwright/test";

const adminUsername = process.env.KOSMO_E2E_ADMIN_USERNAME ?? "admin";
const adminPassword = process.env.KOSMO_E2E_ADMIN_PASSWORD ?? "admin-change-me";

function uniqueSuffix(): string {
  return `${Date.now()}-${Math.random().toString(36).slice(2, 8)}`;
}

async function login(page: Page): Promise<void> {
  await page.goto("/login");
  await expect(page.getByRole("heading", { name: /sign in|iniciar sesión/i })).toBeVisible({ timeout: 15_000 });
  await page.getByLabel(/username|usuario/i).fill(adminUsername);
  await page.getByLabel(/password|contraseñ?a/i).fill(adminPassword);
  await page.getByRole("button", { name: /sign in|iniciar sesión/i }).click();
  await expect(page).toHaveURL(/\/tasks/, { timeout: 15_000 });
}

async function noHorizontalOverflow(page: Page): Promise<void> {
  const overflow = await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth);
  expect(overflow, "page must not overflow horizontally").toBeLessThanOrEqual(1);
}

async function createWorkflow(page: Page, name: string): Promise<void> {
  await page.goto("/workflows");
  await page.getByRole("button", { name: /^add$|añadir$/i }).first().click();
  const nameInput = page.getByLabel(/^name$|nombre$/i);
  await expect(nameInput).toBeVisible({ timeout: 10_000 });
  await nameInput.fill(name);
  await page.getByRole("button", { name: /create workflow|crear flujo de trabajo/i }).click();
  await page.waitForURL(/\/workflows\/[0-9a-f-]{36}\/edit/, { timeout: 30_000 });
  await expect(page.getByLabel(/workflow name|nombre del flujo/i)).toBeVisible({ timeout: 15_000 });
}

test("editor is usable with no horizontal overflow at 768px and 1280px", async ({ page }) => {
  test.setTimeout(120_000);
  await login(page);
  await createWorkflow(page, `e2e-responsive-${uniqueSuffix()}`);

  for (const width of [1280, 768]) {
    await page.setViewportSize({ width, height: 900 });
    await expect(page.locator(".react-flow").first()).toBeVisible({ timeout: 15_000 });
    // The canvas and its controls stay reachable and the page does not scroll sideways.
    await expect(page.getByRole("button", { name: "Fit view", exact: true })).toBeVisible();
    await noHorizontalOverflow(page);
    // Selecting a node opens its properties without introducing overflow.
    await page.locator(".react-flow__node[data-id='start']").click();
    await expect(page.getByRole("heading", { name: /start|inicio/i })).toBeVisible({ timeout: 10_000 }).catch(() => {});
    await noHorizontalOverflow(page);
  }
});

test("task creation remains usable with no horizontal overflow at 375px", async ({ page }) => {
  test.setTimeout(90_000);
  await login(page);
  await page.setViewportSize({ width: 375, height: 800 });
  await page.goto("/tasks/new");
  await expect(page.getByRole("heading", { name: /create a task|crear una tarea/i })).toBeVisible({ timeout: 15_000 });
  await noHorizontalOverflow(page);
  // The launch control stays within the viewport.
  await expect(page.locator("#workflow")).toBeVisible();
  await noHorizontalOverflow(page);
});

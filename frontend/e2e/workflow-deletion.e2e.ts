// Workflow deletion browser journey (WF-DEL-01/03/08).
//
// Creates a workflow through the list dialog, then deletes it from the row
// action and asserts the confirmation dialog and the list update against the
// real compose stack. Runs as the seeded admin (workflow mutations require
// admin/builder). The journey removes the workflow it creates, so it leaves no
// residue. The task checkbox / in-progress states are covered by the unit tests
// (frontend/src/features/workflows/WorkflowListPage.test.tsx).
//
// Prerequisites: compose stack up and seeded (`just up`, `just seed`).
//   pnpm -C frontend exec playwright test e2e/workflow-deletion.e2e.ts

import { expect, test, type Page } from "@playwright/test";

const adminUsername = process.env.KOSMO_E2E_ADMIN_USERNAME ?? "admin";
const adminPassword = process.env.KOSMO_E2E_ADMIN_PASSWORD ?? "admin-change-me";

function uniqueSuffix(): string {
  return `${Date.now()}-${Math.random().toString(36).slice(2, 8)}`;
}

async function loginAdmin(page: Page): Promise<void> {
  await page.goto("/login");
  await expect(page.getByRole("heading", { name: /sign in|iniciar sesión/i })).toBeVisible({ timeout: 15_000 });
  await page.getByLabel(/username|usuario/i).fill(adminUsername);
  await page.getByLabel(/password|contraseñ?a/i).fill(adminPassword);
  await page.getByRole("button", { name: /sign in|iniciar sesión/i }).click();
  await expect(page).toHaveURL(/\/tasks/, { timeout: 15_000 });
}

async function createWorkflow(page: Page, name: string): Promise<void> {
  await page.goto("/workflows");
  await expect(page.getByRole("heading", { name: /workflows|flujos de trabajo/i })).toBeVisible({ timeout: 15_000 });
  await page.getByRole("button", { name: /^add$|añadir$/i }).first().click();
  const nameInput = page.getByLabel(/^name$|nombre$/i);
  await expect(nameInput).toBeVisible({ timeout: 10_000 });
  await nameInput.fill(name);
  await page.getByRole("button", { name: /create workflow|crear flujo de trabajo/i }).click();
  await page.waitForURL(/\/workflows\/[0-9a-f-]{36}\/edit/, { timeout: 30_000 });
}

test("deletes a workflow from the list and removes it", async ({ page }) => {
  test.setTimeout(120_000);
  await loginAdmin(page);
  const name = `e2e-delete-${uniqueSuffix()}`;
  await createWorkflow(page, name);

  await page.goto("/workflows");
  const row = page.getByRole("listitem", { name });
  await expect(row).toBeVisible({ timeout: 15_000 });

  const rowActions = row.getByRole("group");
  await rowActions.getByRole("button", { name: /delete|eliminar/i }).click();

  const dialog = page.getByRole("dialog");
  await expect(dialog).toBeVisible({ timeout: 10_000 });
  await expect(dialog.getByRole("heading", { name: /delete workflow|eliminar flujo de trabajo/i })).toBeVisible();
  // The dialog names the workflow being deleted.
  await expect(dialog.getByText(name)).toBeVisible();

  const confirm = dialog.getByRole("button", { name: /^delete$|^eliminar$/i });
  await expect(confirm).toBeEnabled();
  await confirm.click();

  // The dialog closes and the workflow row is gone from the refreshed list.
  await expect(dialog).not.toBeVisible({ timeout: 15_000 });
  await expect(page.getByRole("listitem", { name })).toHaveCount(0);
});

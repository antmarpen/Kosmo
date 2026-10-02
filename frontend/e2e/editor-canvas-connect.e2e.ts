// Editor canvas regression coverage (editor work-package ownership).
//
// Guards two coupled invariants of the editor layout at the 1280x720 E2E
// viewport, which the phase-2 authoring journeys exercise end-to-end:
//
//   1. The canvas container is height-locked to the visible viewport. The
//      properties panel content (AI agent form, Start field builder) is much
//      taller than the canvas; nothing in the flex chain may grow the canvas
//      with it, because React Flow measures the canvas box and fitView
//      centers within it — an inflated canvas silently pushes every node
//      handle below the fold.
//   2. Dragging from a source handle to a target handle still creates an edge
//      after a tall panel has been open and the view has been refitted — the
//      exact interaction the phase-2 authoring journey performs.
import { expect, test, type Page } from "@playwright/test";

test.use({ viewport: { width: 1280, height: 720 } });

const VIEWPORT_HEIGHT = 720;
const HEADER_HEIGHT = 56; // AppShell header h-14 (3.5rem)

async function login(page: Page): Promise<void> {
  await page.goto("/login");
  await expect(page.getByRole("heading", { name: /sign in|iniciar sesión/i })).toBeVisible({ timeout: 15_000 });
  await page.getByLabel(/username|usuario/i).fill(process.env.KOSMO_E2E_ADMIN_USERNAME ?? "admin");
  await page.getByLabel(/password|contraseñ?a/i).fill(process.env.KOSMO_E2E_ADMIN_PASSWORD ?? "admin-change-me");
  await page.getByRole("button", { name: /sign in|iniciar sesión/i }).click();
  await expect(page).toHaveURL(/\/tasks/, { timeout: 15_000 });
}

async function createWorkflow(page: Page): Promise<void> {
  await page.goto("/workflows");
  await page.getByRole("button", { name: /^add$|añadir$/i }).first().click();
  await page.getByLabel(/^name$|nombre$/i).fill(`editor-canvas-regression-${Date.now()}`);
  await page.getByRole("button", { name: /create workflow|crear flujo de trabajo/i }).click();
  await page.waitForURL(/\/workflows\/[0-9a-f-]{36}\/edit/, { timeout: 30_000 });
}

test("canvas stays viewport-locked with tall panels open and drag-connect creates an edge", async ({ page }) => {
  test.setTimeout(120_000);
  await login(page);
  await createWorkflow(page);

  // The AI properties panel is the tallest panel in the editor; selecting it
  // (palette add opens the panel) must not inflate the canvas container.
  await page.getByRole("button", { name: /^add ai$|añadir ia$/i }).click();
  const canvasBox = await page.locator(".workflow-canvas").boundingBox();
  expect(canvasBox, "canvas must be measurable").toBeTruthy();
  expect(canvasBox!.height).toBeLessThanOrEqual(VIEWPORT_HEIGHT - HEADER_HEIGHT);
  expect(await page.evaluate(() => document.documentElement.scrollHeight)).toBeLessThanOrEqual(VIEWPORT_HEIGHT);

  // fitView must place the Start source handle inside the visible viewport.
  await page.getByRole("button", { name: "Fit view", exact: true }).click();
  await page.waitForTimeout(400);
  const startHandle = await page.locator(".react-flow__node[data-id='start'] .react-flow__handle.source").boundingBox();
  expect(startHandle, "start source handle must be measurable").toBeTruthy();
  expect(startHandle!.y).toBeGreaterThan(0);
  expect(startHandle!.y + startHandle!.height).toBeLessThan(VIEWPORT_HEIGHT);

  // The E2E connect gesture: hover the source handle, press, hover the target
  // handle, release. The edge must appear in the editor model.
  const targetHandle = page.locator(".react-flow__node[data-id='end'] .react-flow__handle.target");
  await page.locator(".react-flow__node[data-id='start'] .react-flow__handle.source").hover();
  await page.mouse.down();
  await targetHandle.hover();
  await page.mouse.up();
  await expect(page.getByTestId("connection-count")).toHaveText(/1/, { timeout: 5_000 });
});

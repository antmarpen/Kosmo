import { expect, test, type APIRequestContext, type Page } from "@playwright/test";

const username = process.env.KOSMO_E2E_ADMIN_USERNAME ?? "admin";
const password = process.env.KOSMO_E2E_ADMIN_PASSWORD ?? "admin-change-me";

async function login(page: Page): Promise<void> {
  await page.goto("/login");
  await page.getByLabel(/username|usuario/i).fill(username);
  await page.getByLabel(/password|contraseñ?a/i).fill(password);
  await page.getByRole("button", { name: /sign in|iniciar sesión/i }).click();
  await expect(page).toHaveURL(/\/tasks/);
}

async function apiToken(request: APIRequestContext): Promise<string> {
  const response = await request.post("/api/auth/login", { data: { username, password } });
  if (!response.ok()) throw new Error(`API login failed: ${response.status()}`);
  return (await response.json()).access_token as string;
}

test("opening a catalog create form moves keyboard focus into the form", async ({ page }) => {
  await login(page);

  await page.goto("/admin/skills");
  await page.getByRole("button", { name: /add|añadir/i }).click();

  await expect(page.getByRole("heading", { name: /add skill|añadir habilidad/i })).toBeVisible();
  await expect(page.getByLabel(/name|nombre/i)).toBeFocused();
});

test("the AI agent selector accepts a keyboard choice and previews agent Markdown", async ({ page, request }) => {
  await login(page);
  const token = await apiToken(request);
  const workflowsResponse = await request.get("/api/workflows", {
    headers: { Authorization: `Bearer ${token}` },
  });
  expect(workflowsResponse.ok()).toBeTruthy();
  const workflows = (await workflowsResponse.json()) as { id: string; name: string }[];
  const reference = workflows.find((workflow) => workflow.name === "reference-security-analysis");
  expect(reference, "the reset seed supplies a reference workflow").toBeTruthy();

  await page.goto(`/workflows/${reference!.id}/edit`);
  await page.locator('.react-flow__node[data-id="summarize"]').click();
  const agent = page.getByRole("combobox", { name: /agent|agente/i });
  await expect(agent).toBeVisible();
  await agent.click();
  await agent.fill("");
  await agent.press("ArrowDown");
  await agent.press("Enter");
  await expect(agent).toHaveValue("reference-security-analysis-agent");

  await page.getByRole("button", { name: /view instructions|ver instrucciones/i }).click();
  const preview = page.getByRole("dialog");
  await expect(preview).toBeVisible();
  await expect(preview).toContainText("Summarize the report accurately");
  await page.getByRole("button", { name: /close|cerrar/i }).click();

  for (const width of [375, 768, 1280]) {
    await page.setViewportSize({ width, height: 900 });
    await expect(page.locator('.react-flow__node[data-id="summarize"]')).toBeVisible();
    await expect(page.getByRole("combobox", { name: /agent|agente/i })).toBeVisible();
    const overflow = await page.evaluate(() => document.documentElement.scrollWidth > window.innerWidth);
    expect(overflow, `workflow editor must not overflow horizontally at ${width}px`).toBe(false);
  }
});

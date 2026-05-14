import { test, expect } from "@playwright/test";

const SAMPLE_SESSIONS = {
  data: [
    {
      id: "sess_01HBCD0XYZABCDEFGHJKMNPQRS",
      agent_id: "agent_01HABCDEFGHJKMNPQRSTVWXYZ",
      agent_version: 1,
      environment_id: null,
      status: "running",
      container_id: null,
      workspace_path: null,
      metadata: { model: "claude-opus-4-7" },
      organization_id: "default",
      workspace_id: "default",
      created_at: new Date(Date.now() - 5 * 60_000).toISOString(),
      updated_at: new Date(Date.now() - 60_000).toISOString(),
    },
  ],
};

test.describe("Sessions list", () => {
  test("redirects to /login when not authenticated", async ({ page }) => {
    await page.goto("/sessions");
    await expect(page).toHaveURL(/\/login/);
    await expect(page.getByRole("heading", { name: /Sign in to Wake/i })).toBeVisible();
  });

  test("signs in and lists sessions via the Wake API", async ({ page, context }) => {
    // Stub the API.
    await context.route("**/v1/sessions*", async (route) => {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify(SAMPLE_SESSIONS),
      });
    });

    await page.goto("/login");
    await page.getByLabel("API key").fill("wake_e2e_key");
    await page.getByRole("button", { name: "Sign in" }).click();

    await expect(page).toHaveURL(/\/sessions/);
    await expect(page.getByRole("heading", { name: "Sessions" })).toBeVisible();
    await expect(page.getByText("claude-opus-4-7")).toBeVisible();
    // Status badge (aria-label) — distingue do <option> no filtro Status.
    await expect(page.getByLabel("Status: Running")).toBeVisible();
    // Tenancy: workspace selector visível na topbar com scope default.
    await expect(page.getByTestId("workspace-selector-trigger")).toBeVisible();
    await expect(page.getByTestId("workspace-selector-trigger")).toContainText("default");
  });
});

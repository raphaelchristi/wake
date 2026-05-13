import { test, expect } from "@playwright/test";

const CREDS = {
  data: [
    {
      vault_id: "v_abc123",
      name: "github_token_demo",
      provider: "github",
      scopes: ["repo", "read:user"],
      created_at: new Date(Date.now() - 60_000).toISOString(),
      expires_at: null,
      metadata: { last_used_at: new Date().toISOString() },
    },
    {
      vault_id: "v_xyz789",
      name: "slack_bot",
      provider: "slack",
      scopes: ["chat:write"],
      created_at: new Date(Date.now() - 3_600_000).toISOString(),
      expires_at: null,
      metadata: {},
    },
  ],
};

const AUDIT = {
  data: [
    {
      timestamp: new Date().toISOString(),
      session_id: "01HZX0EXAMPLE",
      provider: "github",
      host: "api.github.com",
      decision: "allow",
      vault_id: "v_abc123",
      detail: null,
    },
    {
      timestamp: new Date(Date.now() - 30_000).toISOString(),
      session_id: null,
      provider: "github",
      host: null,
      decision: "oauth_success",
      vault_id: "v_abc123",
      detail: null,
    },
  ],
};

test.beforeEach(async ({ context }) => {
  await context.addInitScript(() => {
    window.localStorage.setItem("wake.api_key", "test-key");
  });
});

test.describe("/vault", () => {
  test("renders credentials and surfaces rotate dialog", async ({ page }) => {
    await page.route("**/v1/vault/credentials", async (route) => {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify(CREDS),
      });
    });

    await page.goto("/vault");
    await expect(page.getByTestId("vault-page")).toBeVisible();

    const rows = page.getByTestId("credential-row");
    await expect(rows).toHaveCount(2);
    await expect(page.getByText("github_token_demo")).toBeVisible();
    await expect(page.getByText("slack_bot")).toBeVisible();

    // Open the Add dialog
    await page.getByTestId("open-add-credential").click();
    await expect(page.getByTestId("add-credential-form")).toBeVisible();
    await page.keyboard.press("Escape");
  });

  test("renders the offline state when the backend returns 503", async ({
    page,
  }) => {
    await page.route("**/v1/vault/credentials", async (route) => {
      await route.fulfill({
        status: 503,
        contentType: "application/json",
        body: JSON.stringify({ detail: "Vault not configured" }),
      });
    });

    await page.goto("/vault");
    await expect(page.getByTestId("vault-offline")).toBeVisible();
  });
});

test.describe("/vault/audit", () => {
  test("renders audit rows and filter inputs", async ({ page }) => {
    await page.route("**/v1/vault/audit**", async (route) => {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify(AUDIT),
      });
    });

    await page.goto("/vault/audit");
    await expect(page.getByTestId("vault-audit-page")).toBeVisible();
    await expect(page.getByTestId("audit-row")).toHaveCount(2);
    await expect(page.getByLabel("Provider")).toBeVisible();
    await expect(page.getByLabel("Host")).toBeVisible();
    await expect(page.getByLabel("Decision")).toBeVisible();
    await expect(page.getByLabel("Limit")).toBeVisible();
  });

  test("renders offline state when audit returns 503", async ({ page }) => {
    await page.route("**/v1/vault/audit**", async (route) => {
      await route.fulfill({
        status: 503,
        contentType: "application/json",
        body: JSON.stringify({ detail: "Vault not configured" }),
      });
    });
    await page.goto("/vault/audit");
    await expect(page.getByTestId("audit-offline")).toBeVisible();
  });
});

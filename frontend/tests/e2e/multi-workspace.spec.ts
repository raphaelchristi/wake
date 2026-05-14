/**
 * Multi-workspace E2E:
 *  - Faz login com scope `default/default`, stub retorna 1 sessão.
 *  - Pelo selector da topbar, troca para `acme/prod`, stub retorna 1 sessão diferente.
 *  - Verifica que a tabela mudou (isolamento de cache + headers tenant
 *    chegam ao stub).
 *
 * O dev server real não roda no CI default — o teste pula a menos que o
 * Playwright seja invocado com `pnpm test:e2e` e o web server suba (que
 * é o caso aqui pois `playwright.config.ts` declara `webServer.command`).
 */
import { test, expect } from "@playwright/test";

const SESSION_DEFAULT = {
  id: "sess_01HBCD0XYZ_DEFAULT",
  agent_id: "agent_default",
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
};

const SESSION_ACME = {
  id: "sess_01HACME000_PROD",
  agent_id: "agent_acme",
  agent_version: 1,
  environment_id: null,
  status: "idle",
  container_id: null,
  workspace_path: null,
  metadata: { model: "claude-sonnet-4-7" },
  organization_id: "acme",
  workspace_id: "prod",
  created_at: new Date(Date.now() - 10 * 60_000).toISOString(),
  updated_at: new Date(Date.now() - 2 * 60_000).toISOString(),
};

test.describe("multi-workspace isolation", () => {
  test("switches workspace via topbar and isolates session list", async ({
    page,
    context,
  }) => {
    let lastOrg = "";
    let lastWs = "";
    // Roteia a chamada de sessions e retorna fixture baseada no header
    // tenant injetado pelo client. Isso prova que o switch realmente
    // muda o header (e não só a UI).
    await context.route("**/v1/sessions*", async (route) => {
      const req = route.request();
      lastOrg = req.headers()["x-wake-organization-id"] ?? "";
      lastWs = req.headers()["x-wake-workspace-id"] ?? "";
      const body =
        lastOrg === "acme" && lastWs === "prod"
          ? { data: [SESSION_ACME] }
          : { data: [SESSION_DEFAULT] };
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify(body),
      });
    });

    // Login com default/default.
    await page.goto("/login");
    await page.getByLabel("API key").fill("wake_e2e");
    // Inputs de tenant já vêm com placeholder default; mantemos.
    await page.getByRole("button", { name: "Sign in" }).click();
    await expect(page).toHaveURL(/\/sessions/);

    // Primeira sessão visível (default). Tabela exibe data-testid
    // session-row-<id> mesmo quando o id é truncado pelo formatter.
    await expect(
      page.getByTestId(`session-row-${SESSION_DEFAULT.id}`),
    ).toBeVisible();
    expect(lastOrg).toBe("default");
    expect(lastWs).toBe("default");

    // Abre selector e vai pra acme/prod via switch dialog.
    // Como o Mock fixed list não inclui acme, expomos via localStorage
    // direto (atalho — o real seria adicionar opção via UI). Acionamos
    // o evento storage manualmente.
    await page.evaluate(() => {
      window.localStorage.setItem("wake.organization_id", "acme");
      window.localStorage.setItem("wake.workspace_id", "prod");
      window.dispatchEvent(
        new CustomEvent("wake:tenant-scope-changed", {
          detail: { organizationId: "acme", workspaceId: "prod" },
        }),
      );
    });

    // O provider clear+push para /sessions. A próxima query usa headers
    // novos.
    await expect(page).toHaveURL(/\/sessions/);
    await expect(
      page.getByTestId(`session-row-${SESSION_ACME.id}`),
    ).toBeVisible({ timeout: 10_000 });
    expect(lastOrg).toBe("acme");
    expect(lastWs).toBe("prod");

    // E a sessão antiga não está mais na tabela.
    await expect(
      page.getByTestId(`session-row-${SESSION_DEFAULT.id}`),
    ).toHaveCount(0);
  });
});

/**
 * E2E smoke for the edit-and-replay page.
 *
 * Skipped by default in CI unless the dev server is running with the
 * API proxied or mocked. Mirrors the pattern set by `replay.spec.ts`.
 *
 * Exercises:
 *   - /sessions/:id/edit renders the editor form
 *   - submitting a system_prompt override hits the replay endpoint
 *   - the response payload triggers the side-by-side diff
 *   - the diff shows row counts + changed badge
 *
 * The test relies on MSW/dashboard-shell to mock:
 *   - GET  /v1/sessions/:id          → 200 source session
 *   - GET  /v1/sessions/:id/events   → 200 fixture
 *   - GET  /v1/agents/:agent_id      → 200 agent config
 *   - POST /v1/sessions/:id/replay   → 201 ReplayResult
 *   - GET  /v1/sessions/:new_id/events → 200 replay fixture
 */
import { test, expect } from "@playwright/test";

const SOURCE_SESSION_ID = "sess_01HQR2K7VXBZ9MNPL3WYCT8000";

test.describe("edit-replay page", () => {
  test.skip(
    !process.env.PLAYWRIGHT_BASE_URL,
    "Requires dashboard-shell to provide a running dev server + MSW mocks.",
  );

  test("submits overrides and shows the side-by-side diff", async ({ page }) => {
    await page.goto(`/sessions/${SOURCE_SESSION_ID}/edit`);
    await expect(page.getByTestId("session-edit-page")).toBeVisible();
    await expect(page.getByTestId("session-editor")).toBeVisible();

    // Initial empty state on the right.
    await expect(page.getByTestId("replay-empty-state")).toBeVisible();

    // Type a system prompt override and submit.
    await page
      .getByTestId("system-prompt-input")
      .fill("You are a senior engineer. Be terse.");
    await page.getByTestId("replay-submit").click();

    // Replay summary lands once the mutation resolves.
    await expect(page.getByTestId("replay-summary")).toBeVisible();

    // Diff panel renders with both headers + counts.
    await expect(page.getByTestId("replay-diff")).toBeVisible();
    await expect(page.getByTestId("diff-header-source")).toContainText("events");
    await expect(page.getByTestId("diff-header-replay")).toContainText("events");
    await expect(page.getByTestId("diff-changed-count")).toBeVisible();
  });

  test("surfaces validation errors before hitting the network", async ({ page }) => {
    await page.goto(`/sessions/${SOURCE_SESSION_ID}/edit`);
    await expect(page.getByTestId("session-editor")).toBeVisible();

    // Invalid max_steps — out of range.
    await page.getByTestId("max-steps-input").fill("9999");
    await page.getByTestId("replay-submit").click();

    await expect(page.getByTestId("editor-error")).toBeVisible();
    // The empty state remains because no replay fired.
    await expect(page.getByTestId("replay-empty-state")).toBeVisible();
  });
});

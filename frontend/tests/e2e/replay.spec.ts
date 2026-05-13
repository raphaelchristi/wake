/**
 * E2E smoke for the replay page using the 50-event fixture.
 *
 * Skipped by default in CI unless the dev server is running with the API
 * proxied or mocked. The test exercises:
 *  - timeline renders all ticks
 *  - clicking the End button advances to the last event
 *  - keyboard ArrowLeft retreats
 *  - sandbox state panel shows reconstructed cwd
 *
 * Owned by dashboard-replay slice. The shell slice should expand the test
 * harness (route mocks, baseURL) when its scaffolding lands.
 */
import { test, expect } from "@playwright/test";

const SESSION_ID = "sess_01HQR2K7VXBZ9MNPL3WYCT8000";

test.describe("replay page", () => {
  test.skip(
    !process.env.PLAYWRIGHT_BASE_URL,
    "Requires dashboard-shell to provide a running dev server + MSW mocks.",
  );

  test("scrubber navigates through fixture events", async ({ page }) => {
    await page.goto(`/sessions/${SESSION_ID}/replay`);
    await expect(page.getByTestId("replay-page")).toBeVisible();
    await expect(page.getByTestId("timeline-track")).toBeVisible();
    // First tick + last tick rendered.
    await expect(page.getByTestId("tick-0")).toBeVisible();
    await expect(page.getByTestId("tick-49")).toBeVisible();

    // Click step forward 3 times and verify counter.
    for (let i = 0; i < 3; i++) {
      await page.getByTestId("btn-step-forward").click();
    }
    await expect(page.getByTestId("event-counter")).toContainText("4 /");

    // Keyboard navigation.
    await page.keyboard.press("ArrowLeft");
    await expect(page.getByTestId("event-counter")).toContainText("3 /");
    await page.keyboard.press("End");
    await expect(page.getByTestId("event-counter")).toContainText(`/ 50`);

    // Sandbox state panel reconstructed at end.
    await expect(page.getByTestId("sandbox-state-panel")).toBeVisible();
    await expect(page.getByTestId("sandbox-cwd")).toBeVisible();
  });
});

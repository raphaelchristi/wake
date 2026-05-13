import { test, expect } from "@playwright/test";

const SUMMARY = {
  window: {
    code: "24h",
    start: "2025-01-01T00:00:00Z",
    end: "2025-01-02T00:00:00Z",
    bucket_seconds: 1800,
  },
  latency: { p50_ms: 250, p95_ms: 900, p99_ms: 1800, samples: 42 },
  cost: { total_usd: 4.21, avg_per_session_usd: 0.1, max_session_usd: 0.55, samples: 42 },
  throughput: { sessions: 42, per_hour: 1.75 },
  errors: { count: 3, rate: 0.07, sessions_affected: 3 },
  workers_alive: 2,
  queue_depth: 1,
  series: {
    latency: [
      { t: "2025-01-01T00:00:00Z", p50: 200, p95: 800, p99: 1500 },
      { t: "2025-01-01T00:30:00Z", p50: 250, p95: 900, p99: 1800 },
    ],
    cost: [
      { t: "2025-01-01T00:00:00Z", cost_usd: 1.1 },
      { t: "2025-01-01T00:30:00Z", cost_usd: 3.11 },
    ],
    throughput: [
      { t: "2025-01-01T00:00:00Z", sessions: 20 },
      { t: "2025-01-01T00:30:00Z", sessions: 22 },
    ],
    errors: [
      { t: "2025-01-01T00:00:00Z", errors: 1 },
      { t: "2025-01-01T00:30:00Z", errors: 2 },
    ],
  },
};

const WORKERS = {
  data: [
    {
      worker_id: "w-prod-1",
      status: "alive" as const,
      last_heartbeat_at: new Date().toISOString(),
      current_session_id: "s-abc",
      current_sessions: ["s-abc"],
    },
    {
      worker_id: "w-prod-2",
      status: "stale" as const,
      last_heartbeat_at: new Date(Date.now() - 60_000).toISOString(),
      current_session_id: null,
      current_sessions: [],
    },
  ],
};

test.beforeEach(async ({ context }) => {
  // Seed an API key into localStorage so the (authed) layout doesn't
  // bounce us to /login. The shell slice's auth.ts reads from this exact
  // key — see frontend/src/lib/auth.ts.
  await context.addInitScript(() => {
    window.localStorage.setItem("wake.api_key", "test-key");
  });
});

test.describe("/metrics", () => {
  test("renders the six stat cards and four chart cards with mocked data", async ({
    page,
  }) => {
    await page.route("**/v1/metrics/summary**", async (route) => {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify(SUMMARY),
      });
    });
    await page.route("**/v1/workers", async (route) => {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify(WORKERS),
      });
    });

    await page.goto("/metrics");
    await expect(page.getByTestId("metrics-page")).toBeVisible();

    // Six stat cards
    await expect(page.getByTestId("stat-card")).toHaveCount(6);

    // Chart cards have visible titles
    await expect(page.getByRole("heading", { name: "Latency" })).toBeVisible();
    await expect(page.getByRole("heading", { name: "Cost" })).toBeVisible();
    await expect(page.getByRole("heading", { name: "Throughput" })).toBeVisible();
    await expect(page.getByRole("heading", { name: "Errors" })).toBeVisible();

    // Worker grid
    await expect(page.getByTestId("worker-grid")).toBeVisible();
    await expect(page.getByTestId("worker-card")).toHaveCount(2);

    // Time range picker switches windows
    await page.getByRole("radio", { name: "7d" }).click();
    await expect(page.getByRole("radio", { name: "7d" })).toHaveAttribute(
      "aria-checked",
      "true",
    );
  });

  test("shows error card when /metrics/summary 500s", async ({ page }) => {
    await page.route("**/v1/metrics/summary**", async (route) => {
      await route.fulfill({
        status: 500,
        contentType: "application/json",
        body: JSON.stringify({ detail: "kaboom" }),
      });
    });
    await page.route("**/v1/workers", async (route) => {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({ data: [] }),
      });
    });

    await page.goto("/metrics");
    await expect(page.getByTestId("metrics-error")).toBeVisible();
  });
});

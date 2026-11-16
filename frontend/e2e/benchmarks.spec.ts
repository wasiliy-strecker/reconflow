import { expect, test } from "@playwright/test";

test("comparison loads details separately and renders model output as text", async ({
  page,
}) => {
  const result = {
    protocol: "test-fixture-only",
    model: "gemma3:4b-it-q4_K_M",
    options: { num_ctx: 4096, num_predict: 512 },
    metadata: {
      gpu: "TEST GPU",
      driver: "test",
      runtime_version: "test",
      model_digest: "a".repeat(64),
      quantization: "Q4_K_M",
      download_ms: 100,
      load_ms: 20,
    },
    summary: {
      count: 1,
      median_tokens_per_second: 50,
      min_tokens_per_second: 50,
      max_tokens_per_second: 50,
      median_ttft_ms: 20,
      median_elapsed_ms: 100,
      peak_vram_mib: null,
      gpu_only: true,
    },
  };
  await page.route("**/api/benchmarks/results*", async (route) =>
    route.fulfill({
      json: {
        results: [
          {
            id: "fixture",
            gpu: "TEST GPU",
            model: result.model,
            finished_at: "2026-11-16T12:00:00Z",
            result,
          },
        ],
      },
    }),
  );
  await page.route("**/api/benchmarks/results/fixture", async (route) =>
    route.fulfill({
      json: {
        result: {
          ...result,
          samples: [
            {
              index: 0,
              warmup: false,
              output: '<img src=x onerror="window.injected=true">',
              elapsed_ms: 100,
              ttft_ms: 20,
              tokens_per_second: 50,
              vram_peak_mib: null,
              gpu_only: true,
              eval_count: 5,
            },
          ],
        },
      },
    }),
  );
  await page.goto("/");
  await page
    .getByRole("button", { name: "GPU Benchmarks", exact: true })
    .click();
  await expect(
    page.getByRole("cell", { name: "20 ms", exact: true }),
  ).toBeVisible();
  await page
    .getByRole("checkbox", { name: "Vergleichen TEST GPU fixture" })
    .check();
  await expect(page.getByText("50 Tokens/s", { exact: true })).toBeVisible();
  await page.getByRole("button", { name: "Öffnen", exact: true }).click();
  await page.getByText("Antwort 1", { exact: true }).click();
  await expect(page.locator("pre")).toContainText("<img src=x");
  await expect(
    page.locator('section[aria-label="Messbericht"] img'),
  ).toHaveCount(0);
});

test("GPU area exposes disabled real execution and an honest empty comparison", async ({
  page,
}) => {
  const errors: string[] = [];
  page.on("pageerror", (error) => errors.push(error.message));
  await page.goto("/");
  await page
    .getByRole("button", { name: "GPU Benchmarks", exact: true })
    .click();
  await expect(
    page.getByRole("heading", { name: "GPU Benchmarks." }),
  ).toBeVisible();
  await expect(
    page.getByText("GPU-Mieten sind noch nicht freigeschaltet."),
  ).toBeVisible();
  await expect(
    page.getByRole("button", { name: "GPU mieten und Benchmark starten" }),
  ).toBeDisabled();
  await expect(
    page.getByText("Noch keine echten Benchmark-Ergebnisse vorhanden."),
  ).toBeVisible();
  await page.getByRole("button", { name: "Angebote laden" }).click();
  await expect(page.getByRole("alert")).toContainText(
    "Vast.ai ist noch nicht verbunden.",
  );
  await page.setViewportSize({ width: 390, height: 844 });
  await expect(
    page.getByRole("heading", { name: "GPU Benchmarks." }),
  ).toBeVisible();
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= window.innerWidth,
    ),
  ).toBeTruthy();
  expect(errors).toEqual([]);
});

test("GPU controls send one idempotent rental and request cleanup", async ({
  page,
}) => {
  // Browser-only contract fixture: never inserted into the application database.
  const offer = {
    id: 42,
    gpu: "TEST GPU",
    vram_mib: 16384,
    hourly_usd: "0.20",
    estimated_eur: "0.12",
    within_budget: true,
    download_usd_gb: "0",
    upload_usd_gb: "0",
    storage_usd_gb_month: "0.1",
  };
  let lease: Record<string, unknown> | null = null;
  let calls = 0;
  await page.route("**/api/benchmarks/**", async (route) => {
    const path = new URL(route.request().url()).pathname;
    let response: unknown = {};
    if (path.endsWith("/config"))
      response = {
        enabled: true,
        configured: true,
        monthly_budget_eur: "10",
        session_budget_eur: "1",
        max_minutes: 30,
        idle_seconds: 300,
        protocol: "test-only",
        models: [
          {
            id: "gemma3:4b-it-q4_K_M",
            min_vram_mib: 7680,
            quantization: "Q4_K_M",
            digest: "a".repeat(64),
          },
        ],
        prompts: [{ id: "explain", text: "Synthetic fixture" }],
      };
    else if (path.endsWith("/offers"))
      response = { offers: [offer], available: true };
    else if (path.endsWith("/results")) response = { results: [] };
    else if (path.endsWith("/workspace"))
      response = {
        leases: lease ? [lease] : [],
        requests: [],
        operator: false,
        budget: null,
      };
    else if (path.endsWith("/leases")) {
      calls++;
      expect(route.request().headers()["idempotency-key"]).toBeTruthy();
      expect(route.request().postDataJSON().offer_id).toBe(42);
      lease = {
        id: "test-lease",
        model: "gemma3:4b-it-q4_K_M",
        mode: "suite",
        status: "starting",
        offer,
        reserved_eur: "1",
        estimated_eur: "0.12",
        debited_eur: null,
        deadline_at: new Date(Date.now() + 1800000).toISOString(),
        error: null,
      };
      response = lease;
    } else if (path.endsWith("/stop")) {
      lease = { ...lease, status: "stopping" };
      response = lease;
    }
    await route.fulfill({ json: response });
  });
  await page.goto("/");
  await page
    .getByRole("button", { name: "GPU Benchmarks", exact: true })
    .click();
  await page.getByRole("button", { name: "Angebote laden" }).click();
  await page.getByRole("radio").check();
  await page
    .getByRole("button", { name: "GPU mieten und Benchmark starten" })
    .click();
  await expect(page.getByText("Modell wird geladen")).toBeVisible();
  expect(calls).toBe(1);
  await page
    .getByRole("button", { name: "GPU freigeben", exact: true })
    .click();
  await expect(page.getByText("GPU wird freigegeben")).toBeVisible();
  await expect(
    page.getByRole("button", { name: "GPU freigeben", exact: true }),
  ).toBeDisabled();
});

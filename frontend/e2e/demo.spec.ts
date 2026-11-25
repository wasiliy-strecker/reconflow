import { test, expect, type Page } from "@playwright/test";
import { readFile } from "node:fs/promises";

// Hold one response so assertions observe the pending UI even on a fast backend.
async function whilePending(
  page: Page,
  path: string,
  check: () => Promise<void>,
) {
  let resume!: () => void;
  const held = new Promise<void>((resolve) => {
    resume = resolve;
  });
  await page.route(
    path,
    async (route) => {
      await held;
      await route.continue();
    },
    { times: 1 },
  );
  try {
    await check();
  } finally {
    resume();
  }
}

test("invoice review, reconciliation, import, manual decision and export", async ({
  page,
}) => {
  const errors: string[] = [];
  page.on("pageerror", (error) => errors.push(error.message));
  await page.goto("/");
  await expect(
    page.getByRole("heading", { name: "Rechnungen verstehen." }),
  ).toBeVisible();
  let releaseSeed!: () => void;
  const holdSeed = new Promise<void>((resolve) => {
    releaseSeed = resolve;
  });
  await page.route("**/api/demo-sessions/seed", async (route) => {
    await holdSeed;
    await route.continue();
  });
  await page.getByRole("button", { name: "Demo starten", exact: true }).click();
  try {
    await expect(page.getByRole("status")).toContainText("Bitte warte kurz");
    await expect(page.locator(".stat-placeholder")).toHaveCount(4);
    await expect(page.locator(".loading-row")).toHaveCount(6);
    await expect(page.getByText("Hier ist Platz für deine Daten")).toBeHidden();
    await expect(
      page.getByRole("button", { name: "Daten werden geladen …" }),
    ).toBeDisabled();
  } finally {
    releaseSeed();
  }
  await expect(page.locator("tbody tr")).toHaveCount(6, { timeout: 60_000 });
  try {
    await expect(page.locator(".demo-loading-note")).toHaveCount(0);
    for (const [index, filename] of [
      [0, "RE-2026-1001.pdf"],
      [1, "RE-2026-1002.png"],
      [4, "RE-2026-1005.jpg"],
    ] as const) {
      const original = page.getByRole("button", {
        name: "Original herunterladen: " + filename,
        exact: true,
      });
      const pendingDownload = page.waitForEvent("download");
      await original.click();
      const downloaded = await pendingDownload;
      expect(downloaded.suggestedFilename()).toBe(filename);
      const fixture = await page.request.get("/api/examples/" + index);
      expect(fixture.ok()).toBe(true);
      expect(
        (await readFile((await downloaded.path())!)).equals(
          await fixture.body(),
        ),
      ).toBe(true);
      await expect(page.getByRole("dialog")).toHaveCount(0);
    }
    await page
      .getByRole("button", { name: "Rechnung RE-2026-1001", exact: true })
      .click();
    await expect(page.getByRole("dialog")).toBeVisible();
    if (process.env.RECONFLOW_LIVE_AI === "1") {
      await page
        .getByRole("button", { name: "Mit KI auslesen", exact: true })
        .click();
      await expect(
        page.getByText("Mit OpenAI ausgelesen", { exact: true }),
      ).toBeVisible({ timeout: 90_000 });
      await expect(page.getByLabel("Brutto", { exact: true })).toHaveValue(
        "1190.00",
      );
    }
    await whilePending(page, "**/api/invoices/*", async () => {
      const dialog = page.getByRole("dialog");
      await dialog
        .getByRole("button", { name: "Angaben bestätigen", exact: true })
        .click();
      await expect(
        dialog
          .getByRole("status")
          .filter({ hasText: "Rechnung wird bestätigt" }),
      ).toBeInViewport();
    });
    await expect(page.getByRole("dialog")).toHaveCount(0);

    await whilePending(page, "**/api/workspace", async () => {
      await page.reload({ waitUntil: "domcontentloaded" });
      await expect(page.getByRole("status")).toContainText("wieder geladen");
      await expect(page.locator(".stat-placeholder")).toHaveCount(4);
    });
    await expect(page.locator("tbody tr")).toHaveCount(6);

    await whilePending(page, "**/api/reconciliation-runs", async () => {
      await page
        .getByRole("button", { name: "Abgleich starten", exact: true })
        .click();
      await expect(
        page.getByRole("heading", { name: "Ergebnisse des Abgleichs" }),
      ).toBeFocused();
      await expect(page.getByRole("status")).toContainText(
        "Zahlungen werden abgeglichen",
      );
      await expect(page.getByRole("status")).toBeInViewport();
      await expect(
        page.getByRole("button", { name: "Abgleich läuft …" }),
      ).toBeDisabled();
      await expect(page.locator(".stat-placeholder")).toHaveCount(2);
      await expect(page.locator(".loading-row")).toHaveCount(6);
      await expect(
        page.getByText("Bereit für deinen ersten Abgleich"),
      ).toBeHidden();
    });
    await expect(page.locator("tbody .status-MATCHED")).toHaveCount(2, {
      timeout: 60_000,
    });
    await expect(page.locator("tbody .status-PARTIAL")).toHaveCount(1);
    await expect(page.locator("tbody .status-DUPLICATE")).toHaveCount(1);
    // A failed rerun keeps the previous completed results available.
    await page.route(
      "**/api/reconciliation-runs",
      (r) =>
        r.fulfill({
          status: 429,
          json: { detail: "Abgleich zurzeit nicht möglich." },
        }),
      { times: 1 },
    );
    await page
      .getByRole("button", { name: "Abgleich starten", exact: true })
      .click();
    await expect(page.getByRole("alert")).toBeInViewport();
    await expect(page.getByRole("alert")).toContainText(
      "Abgleich zurzeit nicht möglich.",
    );
    await expect(page.locator("tbody .status-MATCHED")).toHaveCount(2);
    await page
      .getByRole("alert")
      .getByRole("button", { name: "Meldung schließen" })
      .click();
    if (process.env.CAPTURE_SCREENSHOTS === "1")
      await page.screenshot({ path: "../docs/screenshot.png", fullPage: true });
    await page
      .getByRole("row")
      .filter({ hasText: "Unzugeordnete Zahlung" })
      .getByRole("button")
      .click();
    const assignment = page.getByRole("dialog", {
      name: "Zu welcher Rechnung gehört diese Zahlung?",
    });
    await expect(
      assignment.getByText("Vielen Dank fuer das Projekt"),
    ).toBeVisible();
    await expect(assignment.getByText("Eingegangener Betrag")).toBeVisible();
    await expect(
      assignment.getByText(/Betrag und Währung passen/),
    ).toBeVisible();
    await expect(
      assignment.getByText("Rechnungsbetrag", { exact: true }),
    ).toBeVisible();
    await expect(assignment.getByText("Erwartet", { exact: true })).toHaveCount(
      0,
    );
    await expect(assignment.getByText("NO_REFERENCE")).toHaveCount(0);
    await assignment.getByRole("button", { name: "Offen lassen" }).click();
    const unmatched = page
      .getByRole("row")
      .filter({ hasText: "Unzugeordnete Zahlung" });
    await expect(unmatched).toBeVisible();
    await unmatched.getByRole("button").click();
    if (process.env.RECONFLOW_LIVE_AI === "1") {
      await page.getByRole("button", { name: "KI-Vorschlag einholen" }).click();
      await expect(page.getByText("KI-Vorschlag", { exact: true })).toBeVisible(
        { timeout: 90_000 },
      );
    }
    const choice = assignment.getByRole("article", { name: "RE-2026-1005" });
    await expect(choice).toContainText("Mira Kunsthandel");
    await expect(choice).toContainText("833,00");
    await choice
      .getByRole("button", { name: "Zahlung dieser Rechnung zuordnen" })
      .click();
    await expect(page.locator("tbody .status-MATCHED")).toHaveCount(3, {
      timeout: 60_000,
    });
    const download = page.waitForEvent("download");
    await page.getByRole("button", { name: "Excel", exact: true }).click();
    const file = await download;
    expect(file.suggestedFilename()).toBe("ReconFlow-Abgleich.xlsx");
    const path = await file.path();
    expect((await readFile(path!)).subarray(0, 2).toString()).toBe("PK");
    await page
      .getByRole("button", { name: "CSV importieren", exact: true })
      .click();
    const fixture = await page.request.get("/api/examples-payments");
    await page.locator("input[type=file]").setInputFiles({
      name: "payments.csv",
      mimeType: "text/csv",
      buffer: await fixture.body(),
    });
    await expect(
      page.getByText(
        "0 Einträge importiert. 6 bereits vorhandene Einträge übersprungen.",
      ),
    ).toBeVisible();
    await page.setViewportSize({ width: 390, height: 844 });
    await expect(
      page.getByRole("heading", { name: "Jede Zahlung an ihrem Platz." }),
    ).toBeVisible();
    expect(
      await page.evaluate(
        () => document.documentElement.scrollWidth <= window.innerWidth,
      ),
    ).toBe(true);
    if (process.env.CAPTURE_SCREENSHOTS === "1")
      await page.screenshot({
        path: "../docs/screenshot-mobile.png",
        fullPage: true,
      });
    expect(errors).toEqual([]);
    await page.getByRole("button", { name: "Sitzung zurücksetzen" }).click();
    await expect(
      page.getByRole("button", { name: "Demo starten", exact: true }),
    ).toBeVisible();
    await expect(page.locator("tbody tr")).toHaveCount(0);
  } finally {
    const csrf = await page.evaluate(() => sessionStorage.getItem("rf_csrf"));
    if (csrf)
      await page.request.delete("/api/demo-sessions/current", {
        headers: {
          "x-csrf-token": csrf,
          Origin: process.env.DEMO_URL || "http://localhost:5173",
        },
      });
  }
});

test("a failed demo start clears the placeholders and allows another attempt on mobile", async ({
  page,
}) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.emulateMedia({ reducedMotion: "reduce" });
  let failStart!: () => void;
  const holdStart = new Promise<void>((resolve) => {
    failStart = resolve;
  });
  await page.route("**/api/demo-sessions", async (route) => {
    await holdStart;
    await route.fulfill({
      status: 429,
      json: { detail: "Bitte später erneut versuchen." },
    });
  });
  await page.goto("/");
  const start = page.getByRole("button", { name: "Demo starten", exact: true });
  await start.click();
  try {
    await expect(page.getByRole("status")).toContainText("Bitte warte kurz");
    await expect(page.locator(".loading-row").first()).toBeVisible();
    await expect(page.locator(".skeleton").first()).toHaveCSS(
      "animation-name",
      "none",
    );
    expect(
      await page.evaluate(
        () => document.documentElement.scrollWidth <= innerWidth,
      ),
    ).toBe(true);
  } finally {
    failStart();
  }
  await expect(page.getByRole("alert")).toContainText(
    "Bitte später erneut versuchen.",
  );
  await expect(page.locator(".skeleton")).toHaveCount(0);
  await expect(start).toBeEnabled();
});

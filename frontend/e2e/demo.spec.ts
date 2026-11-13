import { test, expect } from "@playwright/test";
import { readFile } from "node:fs/promises";

test("invoice review, reconciliation, import, manual decision and export", async ({
  page,
}) => {
  const errors: string[] = [];
  page.on("pageerror", (error) => errors.push(error.message));
  await page.goto("/");
  await expect(
    page.getByRole("heading", { name: "Rechnungen verstehen." }),
  ).toBeVisible();
  await page.getByRole("button", { name: "Demo starten", exact: true }).click();
  await expect(page.locator("tbody tr")).toHaveCount(6, { timeout: 60_000 });
  try {
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
    await page
      .getByRole("button", { name: "Angaben bestätigen", exact: true })
      .click();
    await expect(page.getByRole("dialog")).toHaveCount(0);
    await page
      .getByRole("button", { name: "Abgleich starten", exact: true })
      .click();
    await expect(
      page.getByRole("heading", { name: "Jede Zahlung an ihrem Platz." }),
    ).toBeVisible({ timeout: 30_000 });
    await expect(page.locator("tbody .status-MATCHED")).toHaveCount(2);
    await expect(page.locator("tbody .status-PARTIAL")).toHaveCount(1);
    await expect(page.locator("tbody .status-DUPLICATE")).toHaveCount(1);
    if (process.env.CAPTURE_SCREENSHOTS === "1")
      await page.screenshot({ path: "../docs/screenshot.png", fullPage: true });
    await page
      .getByRole("row")
      .filter({ hasText: "Unzugeordnete Zahlung" })
      .getByRole("button")
      .click();
    if (process.env.RECONFLOW_LIVE_AI === "1") {
      await page
        .getByRole("button", { name: "KI um einen Zuordnungsvorschlag bitten" })
        .click();
      await expect(page.getByText("KI-Vorschlag", { exact: true })).toBeVisible(
        { timeout: 90_000 },
      );
    }
    await page.getByRole("button", { name: "Zuordnen", exact: true }).click();
    await expect(page.locator("tbody .status-MATCHED")).toHaveCount(3);
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
    await page
      .locator("input[type=file]")
      .setInputFiles({
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
  } finally {
    const csrf = await page.evaluate(() => sessionStorage.getItem("rf_csrf"));
    await page.request.delete("/api/demo-sessions/current", {
      headers: {
        "x-csrf-token": csrf || "",
        Origin: process.env.DEMO_URL || "http://localhost:5173",
      },
    });
  }
});

import { expect, test } from "@playwright/test";

test.beforeEach(async ({ page }) => {
  await page.goto("/login");
  await page.getByLabel("User").fill("radiologist");
  await page.getByLabel("Password").fill(process.env.AURALANE_DEV_PASSWORD);
  await page.getByRole("button", { name: "Sign in" }).click();
  await expect(page.getByTestId("study-row").first()).toBeVisible();
});

test("chest study displays, overlay is off by default and follows zoom", async ({ page }) => {
  await page.getByTestId("study-row").filter({ hasText: "Nodule" }).first().click();
  const viewport = page.getByTestId("viewport");
  await expect(viewport.locator("canvas").first()).toBeVisible();
  // Rendered pixels, not an empty black box: an X-ray compresses far worse.
  await expect.poll(async () => (await viewport.screenshot()).length, { timeout: 15_000 })
    .toBeGreaterThan(60_000);
  await expect(page.getByRole("note", { name: "Non-diagnostic notice" })).toBeVisible();

  await expect(page.getByTestId("rationale-toggle")).toHaveText("Triage rationale: off");
  await expect(page.getByTestId("overlay-layer")).toHaveCount(0);

  await page.getByTestId("rationale-toggle").click();
  const layer = page.getByTestId("overlay-layer");
  await expect(layer).toBeVisible();
  const before = await layer.boundingBox();
  const vp = await viewport.boundingBox();
  expect(before.x).toBeGreaterThanOrEqual(vp.x - 1);
  expect(before.x + before.width).toBeLessThanOrEqual(vp.x + vp.width + 1);
  await page.screenshot({ path: "test-results/study-chest.png" });

  await page.getByRole("button", { name: "Zoom" }).click();
  const cx = vp.x + vp.width / 2, cy = vp.y + vp.height / 2;
  await page.mouse.move(cx, cy);
  await page.mouse.down();
  await page.mouse.move(cx, cy - 120, { steps: 8 });
  await page.mouse.up();
  await expect.poll(async () => (await layer.boundingBox()).width).not.toBeCloseTo(before.width, 0);

  await page.getByTestId("rationale-toggle").click();
  await expect(page.getByTestId("overlay-layer")).toHaveCount(0);
});

test("brain study offers the four series by sequence name", async ({ page }) => {
  await page.getByTestId("study-row").filter({ hasText: "MR Brain" }).first().click();
  const series = page.getByRole("group", { name: "Series" });
  await expect(series.getByRole("button")).toHaveText(["T1C", "T1", "T2", "FLAIR"]);
  await expect(page.getByText("No images are available for this series")).toBeVisible();
  await series.getByRole("button", { name: "FLAIR" }).click();
  await expect(series.getByRole("button", { name: "FLAIR" })).toHaveAttribute("aria-pressed", "true");
});

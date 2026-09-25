import { expect, test } from "@playwright/test";

async function signIn(page, user) {
  await page.goto("/login");
  await page.getByLabel("User").fill(user);
  await page.getByLabel("Password").fill(process.env.AURALANE_DEV_PASSWORD);
  await page.getByRole("button", { name: "Sign in" }).click();
}

test("a radiologist's verdict appears in the admin audit log; admins cannot open it", async ({ browser }) => {
  const rad = await (await browser.newContext()).newPage();
  await signIn(rad, "radiologist");
  await rad.goto("/studies/fixture-cr-ST-028");
  await rad.getByRole("button", { name: "Disagree" }).click();
  await expect(rad.getByText(/^Disagreed by /)).toBeVisible();
  const radToken = await rad.evaluate(() => JSON.parse(sessionStorage.getItem("auralane.session")).token);
  expect((await rad.request.get("/api/admin/audit", { headers: { Authorization: `Bearer ${radToken}` } })).status()).toBe(403);

  const page = await (await browser.newContext()).newPage();
  await signIn(page, "admin");
  await expect(page).toHaveURL(/\/admin\/audit$/);
  const audit = page.getByTestId("audit");
  await expect(audit.getByText("fixture-cr-ST-028").first()).toBeVisible();
  await expect(audit.getByText(/verdict=disagree/).first()).toBeVisible();
  await expect(page.getByRole("note", { name: "Non-diagnostic notice" })).toBeVisible();
  await page.screenshot({ path: "test-results/admin-audit.png", fullPage: true });

  await page.getByRole("link", { name: "Lane mix" }).click();
  await expect(page.getByTestId("lane-mix")).toContainText("NEEDS HUMAN TRIAGE");
  await page.screenshot({ path: "test-results/admin-lanes.png", fullPage: true });
  await page.getByRole("link", { name: "Thresholds" }).click();
  await expect(page.getByTestId("abstain-band")).toContainText("between 0.35 and 0.6");
  await page.screenshot({ path: "test-results/admin-thresholds.png", fullPage: true });
  await page.getByRole("link", { name: "Model registry" }).click();
  await expect(page.getByTestId("model")).toHaveCount(2);
  await page.screenshot({ path: "test-results/admin-models.png", fullPage: true });

  await page.goto("/studies/fixture-cr-ST-028");
  await expect(page).toHaveURL(/\/admin\/audit$/);
  const token = await page.evaluate(() => JSON.parse(sessionStorage.getItem("auralane.session")).token);
  const res = await page.request.get("/api/studies/fixture-cr-ST-028", { headers: { Authorization: `Bearer ${token}` } });
  expect(res.status()).toBe(403);
});

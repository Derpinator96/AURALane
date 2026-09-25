import { expect, test } from "@playwright/test";

async function signIn(page, user) {
  await page.goto("/login");
  await expect(page.getByRole("note", { name: "Non-diagnostic notice" })).toBeVisible();
  await page.getByLabel("User").fill(user);
  await page.getByLabel("Password").fill(process.env.AURALANE_DEV_PASSWORD);
  await page.getByRole("button", { name: "Sign in" }).click();
}

test("radiologist sees the worklist in lane order with the abstention group", async ({ page }) => {
  await signIn(page, "radiologist");
  await expect(page.getByTestId("study-row").first()).toBeVisible();
  const lanes = await page.getByTestId(/^section-/).evaluateAll(
    (els) => els.map((e) => e.dataset.testid.replace("section-", "")));
  expect(lanes).toEqual(["CRITICAL", "URGENT", "ABSTAIN", "EXPEDITED", "ROUTINE"]);
  await expect(page.getByTestId("section-ABSTAIN").getByRole("heading"))
    .toContainText("NEEDS HUMAN TRIAGE");
  await expect(page.getByRole("note", { name: "Non-diagnostic notice" })).toBeVisible();
  await page.screenshot({ path: "test-results/worklist.png", fullPage: true });

  await page.getByLabel("Lane filter").selectOption("CRITICAL");
  const filtered = await page.getByTestId(/^section-/).evaluateAll(
    (els) => els.map((e) => e.dataset.testid.replace("section-", "")));
  expect(filtered).toEqual(["CRITICAL", "ABSTAIN"]);
});

test("admin lands on admin screens and the API refuses it the worklist", async ({ page }) => {
  await signIn(page, "admin");
  await expect(page).toHaveURL(/\/admin$/);
  await page.goto("/");
  await expect(page).toHaveURL(/\/admin$/);
  const token = await page.evaluate(() => JSON.parse(sessionStorage.getItem("auralane.session")).token);
  const res = await page.request.get("/api/worklist", { headers: { Authorization: `Bearer ${token}` } });
  expect(res.status()).toBe(403);
});

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
  await page.getByTestId("scope-department").click();
  await expect(page.getByTestId("study-row").first()).toBeVisible();
  const lanes = await page.getByTestId(/^section-/).evaluateAll(
    (els) => els.map((e) => e.dataset.testid.replace("section-", "")));
  expect(lanes).toEqual(["Chest-CRITICAL", "Chest-URGENT", "Chest-ABSTAIN", "Chest-EXPEDITED",
                         "Chest-ROUTINE", "Neuro-CRITICAL", "Neuro-URGENT", "Neuro-ABSTAIN"]);
  await expect(page.getByTestId("section-Neuro-ABSTAIN").getByRole("heading"))
    .toContainText("Abstention Tray");
  await expect(page.getByRole("note", { name: "Non-diagnostic notice" })).toBeVisible();
  await page.screenshot({ path: "test-results/worklist.png", fullPage: true });

  await page.getByTestId("filter-button").click();
  await page.getByLabel("Lane filter").selectOption("CRITICAL");
  const filtered = await page.getByTestId(/^section-/).evaluateAll(
    (els) => els.map((e) => e.dataset.testid.replace("section-", "")));
  expect(filtered).toEqual(["Chest-CRITICAL", "Chest-ABSTAIN", "Neuro-CRITICAL", "Neuro-ABSTAIN"]);
});

test("admin lands on admin screens and the API refuses it the worklist", async ({ page }) => {
  await signIn(page, "admin");
  await expect(page).toHaveURL(/\/admin\/pipeline$/);
  await page.goto("/");
  await expect(page).toHaveURL(/\/admin\/pipeline$/);
  const token = await page.evaluate(() => JSON.parse(sessionStorage.getItem("auralane.session")).token);
  const res = await page.request.get("/api/worklist", { headers: { Authorization: `Bearer ${token}` } });
  expect(res.status()).toBe(403);
});

test("the study sheet opens at its default width, widens across the screen, and remembers a width", async ({ page }) => {
  await signIn(page, "radiologist");
  await page.getByTestId("scope-department").click();
  const width = () => page.locator(".sheet-shell").evaluate((el) => Math.round(el.getBoundingClientRect().width));
  await page.getByTestId("study-row").first().click();
  await expect(page.getByTestId("workstation-details-panel")).toBeVisible();
  expect(await width()).toBe(460);

  await page.getByTestId("expand-panel").click();
  await expect(page.getByTestId("expand-panel")).toHaveAttribute("aria-pressed", "true");
  expect(await width()).toBe(1440 - 32);
  await expect(page.getByTestId("latest-case-panel")).toBeVisible();

  await page.getByTestId("expand-panel").click();
  expect(await width()).toBe(460);

  // The grip on the sheet's left edge steps with the arrow keys, and the width is kept for the next study.
  await page.getByTestId("resize-panel").focus();
  await page.keyboard.press("ArrowLeft");
  await page.keyboard.press("ArrowLeft");
  expect(await width()).toBe(556);
  await page.keyboard.press("Escape");
  await expect(page.getByTestId("workstation-details-panel")).toHaveCount(0);
  await page.getByTestId("study-row").nth(1).click();
  await expect(page.getByTestId("workstation-details-panel")).toBeVisible();
  expect(await width()).toBe(556);
});

test("worklist rows are separate cards and none of their text overlaps at a laptop width", async ({ page }) => {
  await page.setViewportSize({ width: 1280, height: 800 });
  await signIn(page, "radiologist");
  await page.getByTestId("scope-department").click();
  await expect(page.getByTestId("study-row").first()).toBeVisible();
  const problems = await page.getByTestId("study-row").evaluateAll((rows) => rows.flatMap((row) => {
    const cs = getComputedStyle(row);
    const cells = [...row.children].map((c) => c.getBoundingClientRect());
    const out = [];
    if (cs.boxShadow === "none") out.push("row has no shadow");
    cells.forEach((a, i) => cells.slice(i + 1).forEach((b) => {
      if (Math.min(a.right, b.right) - Math.max(a.left, b.left) > 2 && Math.min(a.bottom, b.bottom) - Math.max(a.top, b.top) > 2) out.push("cells overlap");
    }));
    return out;
  }));
  expect(problems).toEqual([]);
});

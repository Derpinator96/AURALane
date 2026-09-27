import { expect, test } from "@playwright/test";

// Ship gates: favicon, privacy and terms pages, the non-diagnostic banner and
// the footer on every screen, no builder badge, and no request leaves the
// app's own origin.

const banner = (page) => page.getByRole("note", { name: "Non-diagnostic notice" });

async function signIn(page, user) {
  await page.goto("/login");
  await page.getByLabel("User").fill(user);
  await page.getByLabel("Password").fill(process.env.AURALANE_DEV_PASSWORD);
  await page.getByRole("button", { name: "Sign in" }).click();
}

test("favicon is served and linked", async ({ page, request }) => {
  const res = await request.get("/favicon.svg");
  expect(res.status()).toBe(200);
  expect(res.headers()["content-type"]).toContain("svg");
  await page.goto("/login");
  await expect(page.locator("link[rel=icon]")).toHaveAttribute("href", "/favicon.svg");
});

test("privacy and terms are readable without signing in, from the footer", async ({ page }) => {
  await page.goto("/login");
  await page.getByRole("contentinfo").getByRole("link", { name: "Privacy" }).click();
  await expect(page).toHaveURL(/\/privacy$/);
  await expect(page.getByRole("heading", { level: 1 })).toHaveText("Privacy");
  await expect(page.getByRole("heading", { name: "What never leaves the hospital" })).toBeVisible();
  await expect(banner(page)).toBeVisible();
  await page.screenshot({ path: "test-results/privacy.png", fullPage: true });
  await page.getByRole("contentinfo").getByRole("link", { name: "Terms" }).click();
  await expect(page.getByRole("heading", { level: 1 })).toHaveText("Terms");
  await expect(banner(page)).toBeVisible();
});

test("every screen carries the banner and footer, no badge, no third-party request", async ({ page }) => {
  const origin = "http://127.0.0.1:4173";      // baseURL in playwright.config.js
  const foreign = [];
  page.on("request", (r) => { if (!r.url().startsWith(origin) && !r.url().startsWith("data:") && !r.url().startsWith("blob:")) foreign.push(r.url()); });

  const check = async () => {
    await expect(banner(page)).toBeVisible();
    await expect(page.getByRole("contentinfo")).toContainText("Not a medical device");
    await expect(page.getByText(/made with|built with|powered by/i)).toHaveCount(0);
  };
  await page.goto("/login"); await check();
  await page.goto("/privacy"); await check();
  await page.goto("/terms"); await check();
  await signIn(page, "radiologist");
  await expect(page.getByTestId("study-row").first()).toBeVisible(); await check();
  await page.goto("/studies/fixture-cr-ST-028");
  await expect(page.getByRole("button", { name: "Agree", exact: true })).toBeVisible(); await check();
  await page.getByRole("button", { name: "Sign out" }).click();
  await signIn(page, "admin");
  await expect(page.getByTestId("audit")).toBeVisible(); await check();
  expect(foreign).toEqual([]);
});

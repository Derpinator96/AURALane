import { expect, test } from "@playwright/test";

// Two radiologists in two separate browser sessions: one asks the other for a second opinion, the other
// finds it under Second opinions, reports, and the first reads that report from the dropdown on the study.

async function signIn(browser, user) {
  const context = await browser.newContext({ viewport: { width: 1440, height: 900 } });
  const page = await context.newPage();
  await page.goto("/login");
  await page.getByLabel("User").fill(user);
  await page.getByLabel("Password").fill(process.env.AURALANE_DEV_PASSWORD);
  await page.getByRole("button", { name: "Sign in" }).click();
  await page.getByTestId("scope-department").click().catch(() => {});
  await expect(page.getByTestId("study-row").first()).toBeVisible();
  return page;
}

test("a second opinion: ask, receive, report, read the report from the dropdown", async ({ browser }) => {
  const asker = await signIn(browser, "radiologist");
  await asker.getByTestId("study-row").filter({ hasText: "Nodule" }).first().click();
  const study = await asker.evaluate(() => document.querySelector('[data-testid="study-row"].selected').dataset.study);
  await asker.getByTestId("ask-opinion").click();
  await asker.getByLabel("Reader 1").check();
  await asker.getByTestId("opinion-note").fill("Is the nodule new?");
  await asker.getByTestId("opinion-send").click();
  await expect(asker.getByTestId("opinion-count")).toHaveText("Sent to 1 radiologist");
  await expect(asker.getByTestId("opinion-person")).toContainText("Reader 1Waiting");

  const reader = await signIn(browser, "radiologist-1");
  await expect(reader.getByTestId("nav-opinions")).toContainText("1");
  await reader.getByTestId("nav-opinions").click();
  const row = reader.getByTestId("opinion-row");
  await expect(row).toHaveCount(1);
  await expect(row).toContainText("Is the nodule new?");
  await row.click();
  await expect(reader.getByTestId("opinion-from")).toContainText("requested by");
  await reader.getByTestId("draft-text").fill("EXAMINATION\nChest radiograph.\n\nIMPRESSION\nSecond reader: no change.");
  await reader.getByTestId("draft-reviewed").click();
  await expect(reader.getByTestId("draft-status")).toContainText("Reviewed by");
  await reader.keyboard.press("Escape");
  await expect(reader.getByTestId("opinion-status")).toHaveText("Reported");

  // The one who asked opens the study again: it shows the report is in, and the dropdown reads it.
  await asker.keyboard.press("Escape");
  await asker.goto(`/studies/${encodeURIComponent(study)}`);
  await expect(asker.getByTestId("opinion-person")).toContainText("Reported");
  await asker.getByTestId("report-picker").selectOption({ label: "Reader 1, reviewed" });
  await expect(asker.getByTestId("report-readonly")).toHaveValue(/Second reader: no change\./);
  await expect(asker.getByTestId("report-status")).toContainText("Reviewed by");
  await asker.screenshot({ path: "test-results/second-opinion.png" });
});

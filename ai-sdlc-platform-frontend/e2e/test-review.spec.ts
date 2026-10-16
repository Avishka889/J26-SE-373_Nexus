import { test, expect, type Page } from "@playwright/test";

/**
 * The Testing and Security phase, walked the way a reader walks it.
 *
 * The other two gated phases have this spec for the same reason: a phase whose
 * whole point is a decision needs a check that the decision can be reached and
 * recorded, through the real chrome, at a real width.
 *
 * This one is later than the others because the phase had no shared chrome to
 * walk until it was migrated onto one. It kept six step ids of its own over the
 * contract's seven stages and rendered its own stepper, so every invariant the
 * other phases are held to stopped at its door.
 *
 * NotifyHub (p4) is past the test gate, so its testing phase has everything in
 * it. A phase with nothing generated would pass a walk by having nothing to
 * walk, which is the trap the narrow width sweep records for the same reason.
 */

async function login(page: Page) {
  await page.goto("/login");
  await page.getByLabel(/email/i).fill("alex@acme.dev");
  await page.getByLabel("Password", { exact: true }).fill("demo");
  await page.getByRole("button", { name: "Sign in", exact: true }).click();
  await expect(page).toHaveURL(/\/workspace/);
}

/** Open the phase with the full stage row showing, not the condensed rail. */
async function openTesting(page: Page, projectId: string) {
  await page.goto(`/projects/${projectId}/testing`);
  await expect(page.getByRole("heading", { name: /Testing & Security/ })).toBeVisible();
  await expect(page.locator("[data-stage-rail]")).toBeVisible();
  const hide = page.getByRole("button", { name: /hide the conversation/i }).first();
  if (await hide.isVisible()) await hide.click();
}

test.describe("the testing phase on the shared chrome", () => {
  test("every stage the contract declares has a chevron", async ({ page }) => {
    await login(page);
    await openTesting(page, "p4");

    const steps = page.locator("[data-stage-rail] .overflow-x-auto button");

    // Seven, because that is what the server reports. The phase used to render
    // six of its own, which meant test generation had nowhere to say anything,
    // including that it had been skipped.
    await expect(steps).toHaveCount(7);
  });

  test("each stage opens and names itself", async ({ page }) => {
    await login(page);
    await openTesting(page, "p4");

    const steps = page.locator("[data-stage-rail] .overflow-x-auto button");
    const total = await steps.count();
    const seen: string[] = [];

    for (let i = 0; i < total; i += 1) {
      await steps.nth(i).click();
      await page.waitForTimeout(400);
      const current = await page
        .locator('[aria-current="step"]')
        .first()
        .textContent();
      seen.push((current ?? "").trim());
    }

    // No stage may open onto nothing. A blank stage is how a migration passes
    // a typecheck and fails a reader.
    expect(seen.filter(Boolean)).toHaveLength(total);
  });

  test("the guard's evidence is reachable from the healing stage", async ({ page }) => {
    await login(page);
    await openTesting(page, "p4");

    await page.locator("[data-stage-rail] .overflow-x-auto button", { hasText: "Self Healing" }).click();

    // The refusal is the row this component is judged on, so it has to be on
    // screen rather than behind a filter the reader has to discover.
    await expect(page.getByText(/refused|regression|healed/i).first()).toBeVisible();
  });

  test("the review stage is reachable and is the one on screen", async ({ page }) => {
    await login(page);
    await openTesting(page, "p4");

    await page
      .locator("[data-stage-rail] .overflow-x-auto button", { hasText: "Test Review" })
      .click();
    await page.waitForTimeout(400);

    // The chevron, not a heading: the shell draws a heading only for a stage
    // that has nothing to show, and a stage that ran renders its own body. An
    // assertion on the heading passes exactly when the stage is empty, which
    // is the opposite of what this is for.
    await expect(page.locator('[aria-current="step"]').first()).toContainText("Test Review");
    await expect(page.getByText(/Rollback/i).first()).toBeVisible();
  });
});

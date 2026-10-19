import { test, expect, type Page } from "@playwright/test";

/**
 * The deployment phase, walked the way a reviewer walks it.
 *
 * NotifyHub (p4) is past the test gate. Its deploy version 3 waits at review
 * with one High, two Medium and three Low updates, and its deploy version 2
 * went down in production minutes after release and waits on a person's
 * rollback decision. Both halves of the phase's promise are on this page at
 * once: nothing ships without a person, and nothing rolls back without one.
 *
 * The refusals are asserted in the server's own words, because the fixtures
 * answer with them: a demo that accepted what the orchestrator refuses would
 * be a page that works until the flag flips.
 */

async function login(page: Page) {
  await page.goto("/login");
  await page.getByLabel(/email/i).fill("alex@acme.dev");
  await page.getByLabel("Password", { exact: true }).fill("demo");
  await page.getByRole("button", { name: "Sign in", exact: true }).click();
  await expect(page).toHaveURL(/\/workspace/);
}

/** Open the phase with the full stage row showing, not the condensed rail. */
async function openDeployment(page: Page) {
  await page.goto("/projects/p4/deployment");
  await expect(page.getByRole("heading", { name: /^Deployment$/ })).toBeVisible();
  await expect(page.locator("[data-stage-rail]")).toBeVisible();
  const hide = page.getByRole("button", { name: /hide the conversation/i }).first();
  if (await hide.isVisible()) await hide.click();
}

async function openStage(page: Page, label: string) {
  await page
    .locator("[data-stage-rail] .overflow-x-auto button", { hasText: label })
    .click();
  await expect(page.locator('[aria-current="step"]')).toContainText(label);
}

test.use({ viewport: { width: 1440, height: 900 } });

test.describe("the deployment phase", () => {
  test("every stage the contract declares has a chevron", async ({ page }) => {
    await login(page);
    await openDeployment(page);
    // Ten, which is what the server reports: seven a run produces, the review,
    // and the release and monitoring the orchestrator carries out after it.
    await expect(page.locator("[data-stage-rail] .overflow-x-auto button")).toHaveCount(10);
  });

  test("opens on the release that is down, and rolls nothing back until a person approves", async ({
    page,
  }) => {
    await login(page);
    await openDeployment(page);

    // The most urgent thing on the page is where it opens.
    await expect(page.locator('[aria-current="step"]')).toContainText("Release");
    const decision = page.locator("[data-rollback-decision]");
    await expect(decision).toContainText("Deploy version 2 is down");
    await expect(decision).toContainText("controlled failure");
    const rollbacks = page.getByText(/^Rollback to deploy version/);
    await expect(rollbacks).toHaveCount(0);

    // Declining is a decision too, and it waits for its reason rather than
    // being refused for the lack of one.
    await expect(decision.getByRole("button", { name: "Decline" })).toBeDisabled();
    await expect(rollbacks).toHaveCount(0);

    // Approving asks first, then starts it, back to the last verified release.
    await decision.getByRole("button", { name: /approve the rollback/i }).click();
    const confirm = page.getByRole("alertdialog");
    await expect(confirm).toContainText("Roll back to deploy version 1?");
    await expect(rollbacks).toHaveCount(0);
    await confirm.getByRole("button", { name: "Approve the rollback" }).click();
    await expect(rollbacks.first()).toContainText("Rollback to deploy version 1");
    await expect(page.locator("[data-rollback-decision]")).toHaveCount(0, { timeout: 15_000 });
  });

  test("shows each update's level, verified quote and files together", async ({ page }) => {
    await login(page);
    await openDeployment(page);
    await openStage(page, "Risk Assessment");

    // A minor release SemVer calls Medium, which the release notes make High.
    const card = page.locator('[data-update-card="react-router-dom"]');
    await expect(card.getByText("High", { exact: true })).toBeVisible();
    await expect(card.getByText("decided by Changelog")).toBeVisible();
    // The claims start closed, a package's notes being hundreds of sentences, and
    // what they say by kind stays on the card beside the level and the files.
    const claims = card.getByRole("button", { name: /verified claims?: .*breaking/ });
    await expect(claims).toBeVisible();
    await expect(card.getByText(/"breaking bug fix"/)).toHaveCount(0);
    await claims.click();
    await expect(card.getByText(/"breaking bug fix"/)).toBeVisible();
    await expect(card.getByText("Where the project uses it")).toBeVisible();
    await expect(
      card.getByText(/No file in this project uses a symbol this update changes/),
    ).toBeVisible();
  });

  test("keeps each package's release note claims closed until asked", async ({ page }) => {
    await login(page);
    await openDeployment(page);
    await openStage(page, "Changelog Analysis");

    // A live package's notes ran to 176 claims, and the stage to 13,009px.
    const reactRouter = page.locator("article", { hasText: "react-router-dom" });
    const toggle = reactRouter.getByRole("button", { name: /verified claims?: .*breaking/ });
    await expect(toggle).toHaveAttribute("aria-expanded", "false");
    await expect(reactRouter.getByText(/"breaking bug fix"/)).toHaveCount(0);
    await toggle.click();
    await expect(reactRouter.getByText(/"breaking bug fix"/)).toBeVisible();
  });

  test("shows the generated deployment files in an explorer and an editor", async ({ page }) => {
    await login(page);
    await openDeployment(page);
    await openStage(page, "CI/CD Pipeline");

    // The tree is the files the generation wrote, each tagged with its purpose.
    const files = page.locator("#pipeline-files");
    await expect(files.getByText("Explorer")).toBeVisible();
    await files.getByText("render.yaml", { exact: true }).click();
    // The demo carries each file's name and checks, not its body, and says so
    // where the body would be rather than showing an invented one.
    await expect(files.getByText(/The demo carries this file's name and checks, not its body/)).toBeVisible();
  });

  test("holds a High approval until its review note, and releases once every decision is taken", async ({
    page,
  }) => {
    await login(page);
    await openDeployment(page);
    await openStage(page, "Deployment Review");

    const release = page.getByRole("button", { name: /approve and release/i });
    await expect(release).toBeDisabled();

    // Held rather than refused: the server refuses a High approval with no
    // review note, and the button no longer invites the refusal.
    const high = page.locator('[data-update-decision="react-router-dom"]');
    await expect(high.getByRole("button", { name: "Approve", exact: true })).toBeDisabled();
    await expect(high.getByText(/Approved by/)).toHaveCount(0);

    await high.getByLabel(/review note/i).fill("Checked the CSRF change: the app sets no proxy host.");
    await high.getByRole("button", { name: "Approve", exact: true }).click();
    await expect(high.getByText(/Approved by Alex Chen/)).toBeVisible();

    for (const name of ["supertest", "tailwindcss"]) {
      const medium = page.locator(`[data-update-decision="${name}"]`);
      await medium.getByRole("button", { name: "Approve", exact: true }).click();
      await expect(medium.getByText(/Approved by Alex Chen/)).toBeVisible();
    }

    await expect(release).toBeEnabled();
    await release.click();
    await expect(page.locator('[aria-current="step"]')).toContainText("Release");
    await expect(page.getByText("Release of deploy version 3").first()).toBeVisible();
  });
});

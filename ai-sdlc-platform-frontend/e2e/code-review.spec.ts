import { test, expect, type Page } from "@playwright/test";

/**
 * The Code Generation phase, walked the way a reader walks it.
 *
 * The design phase has the same spec for the same reason: a phase whose whole
 * point is a decision needs a check that the decision can actually be reached
 * and recorded, through the real chrome, at a real width.
 *
 * MediTrack (p2) is the project in `code`, so it is the one with a code review
 * waiting. That is derived from the project's own status rather than written
 * down twice, which is what stops a badge and a phase contradicting each other.
 */

async function login(page: Page) {
  await page.goto("/login");
  await page.getByLabel(/email/i).fill("alex@acme.dev");
  await page.getByLabel(/password/i).fill("demo");
  await page.getByRole("button", { name: /log in/i }).click();
  await expect(page).toHaveURL(/\/workspace/);
}

/**
 * Open the phase with the full stage row showing.
 *
 * The conversation column is remembered open, and open is exactly what
 * condenses the rail to two arrows and a heading. That is correct behaviour
 * and the design phase's spec closes it for the same reason: a check that
 * clicks stage chevrons has to be looking at stage chevrons. Without this the
 * substring "Tech Stack" matches the condensed "Next: Tech Stack" arrow, and
 * a spec that walks the phase by pressing next passes without ever proving a
 * chevron works.
 */
async function openCode(page: Page, projectId: string) {
  await page.goto(`/projects/${projectId}/code`);
  await expect(page.getByRole("heading", { name: "Code Generation" })).toBeVisible();
  // Wait for the phase itself first. The heading renders while the snapshot
  // is still loading, so counting the conversation's controls before this
  // finds none, skips the close, and leaves the rail condensed for the whole
  // spec.
  await expect(page.locator("[data-stage-rail]")).toBeVisible();
  // `.first()`, because the sheet renders the same panel below lg and two
  // matches is a strict mode violation rather than an absent button.
  const hide = page.getByRole("button", { name: /hide the conversation/i }).first();
  if (await hide.isVisible()) await hide.click();
  await expect(page.locator("[data-stage-rail] .overflow-x-auto")).toBeVisible();
}

/** A stage chevron, never the condensed next arrow that shares its words. */
function chevron(page: Page, label: string) {
  return page
    .locator("[data-stage-rail] .overflow-x-auto")
    .getByRole("button", { name: label, exact: false })
    .first();
}

test.use({ viewport: { width: 1440, height: 900 } });

test("the stage column scrolls", async ({ page }) => {
  /**
   * The phase is a fixed height two column layout: its root is `h-full`, and
   * `h-full` resolves against nothing useful if an auto height wrapper sits
   * between it and the shell's bounded row. The route had a `p-2` div there,
   * so the workspace grew to its whole content height (7518px measured, in an
   * 844px main) and nothing scrolled at all. Measured rather than eyeballed,
   * because the page looks identical either way until you try to reach the
   * bottom of it.
   */
  await login(page);
  await openCode(page, "p2");

  const measured = await page.evaluate(() => {
    const sc = document.querySelector("[data-stage-scroller]") as HTMLElement;
    return { client: sc.clientHeight, scroll: sc.scrollHeight, main: document.querySelector("main")!.clientHeight };
  });
  // The scrollport is bounded by the shell, not by its own content.
  expect(measured.client).toBeLessThanOrEqual(measured.main);
  expect(measured.scroll).toBeGreaterThan(measured.client);

  await page.mouse.wheel(0, 700);
  await expect
    .poll(async () =>
      page.evaluate(() => (document.querySelector("[data-stage-scroller]") as HTMLElement).scrollTop),
    )
    .toBeGreaterThan(0);
});

test("the generated files are readable in the explorer and the editor", async ({ page }) => {
  await login(page);
  await openCode(page, "p2");
  await chevron(page, "Frontend Code").click();

  // The tree lists what the run actually wrote, with the manifest's own facts
  // on each row: which generator authored it, and from which contract arm.
  await expect(page.getByText("Explorer")).toBeVisible();
  await expect(page.getByText("client.ts", { exact: false }).first()).toBeVisible();
  // And the editor shows a body, fetched for that file rather than carried by
  // the snapshot.
  await expect(page.locator("pre").first()).toBeVisible();
});

test("every stage is reachable and shows what it generated", async ({ page }) => {
  await login(page);
  await openCode(page, "p2");

  await expect(page.locator("[data-stage-rail]")).toBeVisible();

  // The scope, and the reason it matters, before anything else.
  await expect(page.getByText(/in scope/i).first()).toBeVisible();

  const stages: [string, RegExp][] = [
    ["Tech Stack", /Candidates/],
    ["API Contract", /How this contract was inferred/i],
    ["Frontend Code", /Files \(/],
    ["Backend Code", /Files \(/],
    ["Contract Agreement", /Findings \(/],
    ["Build", /Repository/],
  ];

  for (const [label, expected] of stages) {
    await chevron(page, label).click();
    await expect(page.getByText(expected).first()).toBeVisible();
  }
});

test("the contract names what each endpoint was inferred from", async ({ page }) => {
  await login(page);
  await openCode(page, "p2");
  await chevron(page, "API Contract").click();

  // The claim this platform is built on: an endpoint says where it came from.
  await expect(page.getByText(/Traces to|no screen evidence/i).first()).toBeVisible();
  await expect(page.getByText(/% confidence/i).first()).toBeVisible();
  // Both methods are kept, because comparing them is the point, and named as a
  // developer would name them rather than as the study's "arms". Exact, because
  // the decision bar's summary also says where the contract came from, and
  // matching that would prove the summary exists rather than the comparison.
  await expect(page.getByText("Rule-based", { exact: true })).toBeVisible();
  await expect(page.getByText("AI model", { exact: true })).toBeVisible();
  await expect(page.getByText(/Both agree on/)).toBeVisible();
});

test("the build says what ran and where the code did not go", async ({ page }) => {
  await login(page);
  await openCode(page, "p2");
  await chevron(page, "Build").click();

  await expect(page.getByText("Nothing was pushed")).toBeVisible();
  // The honest reason, not an invented URL.
  await expect(page.getByText(/no GitHub connection/i)).toBeVisible();
  await expect(page.getByText(/Docker is not installed/i)).toBeVisible();
});

test("a project whose design is not approved says so instead of pretending", async ({ page }) => {
  await login(page);
  // ShopFlow is in `design`: its design review has not been approved.
  await openCode(page, "p3");

  await expect(page.getByText("This phase has not started")).toBeVisible();
  // The reason is the server's sentence (the snapshot's designBlocker).
  await expect(page.getByText(/design has not been approved/i)).toBeVisible();
  // No generate button, because there is nothing settled to generate from.
  await expect(page.getByRole("button", { name: /generate code/i })).toHaveCount(0);
});

test("the review can be approved and the decision is recorded", async ({ page }) => {
  await login(page);
  await openCode(page, "p2");

  const decision = page.getByRole("button", { name: /approve code/i });
  await expect(decision).toBeVisible();
  await decision.click();

  await expect(page.getByText(/Approved by/i).first()).toBeVisible();
  // And the decision bar is gone: there is nothing left to decide.
  await expect(page.getByRole("button", { name: /approve code/i })).toHaveCount(0);

  // The way on is on the page, as Requirements and Design gives it: approving
  // left a reviewer on a finished phase with the next one only in the tabs.
  await page.getByRole("button", { name: "Continue to Testing & Security" }).click();
  await expect(page).toHaveURL(/\/projects\/p2\/testing(\?.*)?$/);
});

test("an approved project reads as decided rather than as waiting", async ({ page }) => {
  await login(page);
  // NexusPay is in `testing`, so its code review was approved.
  await openCode(page, "p1");

  await expect(page.getByRole("button", { name: /approve code/i })).toHaveCount(0);
  await chevron(page, "Code Review").click();
  await expect(page.getByText(/Approved by/i).first()).toBeVisible();
});

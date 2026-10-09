import { test, expect, type Page } from "@playwright/test";

/**
 * The section pills double as a position indicator, so they have to be listed in
 * the order the page renders the sections they point at.
 *
 * Wireframes listed Flows before Coverage while the page renders Coverage first,
 * so arriving at the stage lit Flows while the reader was looking at Coverage.
 * The spy reads the id array as page order too, in its fallbacks.
 */
async function login(page: Page) {
  await page.goto("/login");
  await page.getByLabel(/email/i).fill("alex@acme.dev");
  await page.getByLabel(/password/i).fill("demo");
  await page.getByRole("button", { name: /log in/i }).click();
  await expect(page).toHaveURL(/\/workspace/);
}

test.use({ viewport: { width: 1440, height: 900 } });

/**
 * The invariant, for whichever gated phase is on screen.
 *
 * A function rather than two copies: the chrome is shared, so a rule about it
 * that only one phase's spec enforced would be a rule half of the product got
 * to break.
 */
async function checkPillOrder(page: Page, url: string, expectedStages: number) {
  await page.goto(url);
  await expect(page.locator("[data-stage-rail]")).toBeVisible();
  // Closed, so the rail shows every chevron rather than condensing to one.
  // `.first()`, because the phone sheet renders the same panel and two matches
  // is a strict mode violation rather than an absent button.
  const hide = page.getByRole("button", { name: /hide the conversation/i }).first();
  if (await hide.isVisible()) await hide.click();
  await page.waitForTimeout(400);

  const steps = page.locator("[data-stage-rail] .overflow-x-auto button");
  const total = await steps.count();
  expect(total).toBe(expectedStages);

  const checked: string[] = [];
  for (let i = 0; i < total; i += 1) {
    await steps.nth(i).click();
    await page.waitForTimeout(700);

    const seen = await page.evaluate(() => {
      const sc = document.querySelector("[data-stage-scroller]") as HTMLElement;
      const rail = document.querySelector("[data-stage-rail]") as HTMLElement;
      return {
        stage:
          document
            .querySelector('[aria-current="step"]')
            ?.textContent?.trim()
            .slice(0, 30) ?? "unknown",
        // Pills in the order they are offered to the reader.
        pills: Array.from(
          rail.querySelectorAll<HTMLElement>("[data-section]"),
        ).map((b) => b.dataset.section ?? ""),
        // The pill lit on arrival, by the section it points at.
        active:
          rail
            .querySelector('[aria-current="location"]')
            ?.getAttribute("data-section") ?? null,
        // Sections in the order the page lays them out.
        sections: Array.from(sc.querySelectorAll("section.tp-anchor"))
          .map((s) => ({
            id: s.id,
            top: s.getBoundingClientRect().top,
          }))
          .sort((a, b) => a.top - b.top)
          .map((s) => s.id),
      };
    });

    // One section renders no pill row at all, which is deliberate.
    if (seen.pills.length < 2) continue;

    expect(
      seen.pills,
      `the pills on ${seen.stage} are not in the order the page renders them`,
    ).toEqual(seen.sections);
    // A stage opens at the top, so the pill lit must be the one for the section
    // the reader is actually looking at.
    expect(
      seen.active,
      `the wrong pill is lit on arrival at ${seen.stage}`,
    ).toBe(seen.sections[0]);
    checked.push(seen.stage);
  }

  // Without this the loop could match nothing and the test would pass on air.
  expect(checked.length).toBeGreaterThanOrEqual(4);
}

test("every design stage's pills are listed in the order its page reads", async ({
  page,
}) => {
  await login(page);
  await checkPillOrder(page, "/projects/p3/requirements", 8);
});

test("every code stage's pills are listed in the order its page reads", async ({
  page,
}) => {
  await login(page);
  // MediTrack is the project in `code`, so it is the one with every code stage
  // generated and something for each pill to point at.
  await checkPillOrder(page, "/projects/p2/code", 8);
});

test("every testing stage's pills are listed in the order its page reads", async ({
  page,
}) => {
  await login(page);
  // NotifyHub is past the test gate, so every stage has run and every pill has
  // something to point at. Seven stages, which is what the contract declares:
  // this phase used to render six ids of its own and no pills at all, so the
  // rule this file enforces was one the testing phase simply got to break.
  await checkPillOrder(page, "/projects/p4/testing", 7);
});

test("every deployment stage's pills are listed in the order its page reads", async ({
  page,
}) => {
  await login(page);
  // NotifyHub is the project in Deploy, so every analysis stage has run and the
  // release and monitoring stages have a ledger and a window to show. Ten
  // stages, each with at least two sections, so every one of them has pills.
  await checkPillOrder(page, "/projects/p4/deployment", 10);
});

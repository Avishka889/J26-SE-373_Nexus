import { test, expect, type Page } from "@playwright/test";

/**
 * Testing and Deployment scroll in their own stage column, as Code Generation does.
 *
 * Each is a fixed height two column phase: its root is `h-full`, which resolves
 * against the shell's bounded row only when nothing with an auto height sits
 * between them. Both routes kept the `p-2` wrapper that Code Generation lost in
 * 41c9485 for the same reason, so each workspace grew to its whole content
 * height (1901px measured on a live testing page, in an 844px main), its stage
 * column had nothing to scroll, and that column's `overscroll-contain` kept the
 * wheel from the shell's scrollport as well: nothing on the page scrolled.
 * Measured rather than eyeballed, because the page looks identical either way
 * until you try to reach the bottom of it.
 */

test.use({ viewport: { width: 1440, height: 900 } });

async function login(page: Page) {
  await page.goto("/login");
  await page.getByLabel(/email/i).fill("alex@acme.dev");
  await page.getByLabel(/password/i).fill("demo");
  await page.getByRole("button", { name: /log in/i }).click();
  await expect(page).toHaveURL(/\/workspace/);
}

async function scrollTop(page: Page): Promise<number> {
  return page.evaluate(() => (document.querySelector("[data-stage-scroller]") as HTMLElement).scrollTop);
}

for (const phase of ["testing", "deployment"]) {
  test(`the ${phase} stage column scrolls`, async ({ page }) => {
    await login(page);
    await page.goto(`/projects/p4/${phase}`);
    // A first load on a cold development server compiles the phase's modules.
    await expect(page.locator("[data-stage-rail]")).toBeVisible({ timeout: 30_000 });

    const measured = await page.evaluate(() => {
      const scroller = document.querySelector("[data-stage-scroller]") as HTMLElement;
      return {
        client: scroller.clientHeight,
        scroll: scroller.scrollHeight,
        main: document.querySelector("main")!.clientHeight,
      };
    });
    // The scrollport is bounded by the shell, not by its own content.
    expect(measured.client).toBeLessThanOrEqual(measured.main);
    expect(measured.scroll).toBeGreaterThan(measured.client);

    // Over the stage column, where a person reading the phase has the pointer.
    const box = (await page.locator("[data-stage-scroller]").boundingBox())!;
    await page.mouse.move(box.x + box.width / 2, box.y + box.height / 2);
    await page.mouse.wheel(0, 700);
    await expect.poll(() => scrollTop(page)).toBeGreaterThan(0);
  });
}

/**
 * The stage rail stays at the top of the stage column while a stage scrolls, in
 * every phase. Design and Code render it straight inside the column's content,
 * so a sticky rail has the whole column to stick within. Testing and Deployment
 * wrapped it in a div of its own height, which is all a sticky element may stick
 * within, so it scrolled away with that div (1048px off screen on a live test
 * run stage).
 */
for (const [phase, project] of [
  ["requirements", "p3"],
  ["code", "p2"],
  ["testing", "p4"],
  ["deployment", "p4"],
] as const) {
  test(`the ${phase} stage rail stays pinned while the stage scrolls`, async ({ page }) => {
    await login(page);
    await page.goto(`/projects/${project}/${phase}`);
    // A first load on a cold development server compiles the phase's modules.
    await expect(page.locator("[data-stage-rail]")).toBeVisible({ timeout: 30_000 });

    const pinned = await page.evaluate(() => {
      const scroller = document.querySelector("[data-stage-scroller]") as HTMLElement;
      const rail = document.querySelector("[data-stage-rail]") as HTMLElement;
      scroller.scrollTop = scroller.scrollHeight;
      return {
        scrolled: scroller.scrollTop,
        offset: rail.getBoundingClientRect().top - scroller.getBoundingClientRect().top,
      };
    });
    // Far enough to have carried an unpinned rail away, and the rail still on top.
    expect(pinned.scrolled).toBeGreaterThan(200);
    expect(Math.abs(pinned.offset)).toBeLessThanOrEqual(1);
  });
}

/**
 * A transcript scrolls inside a bounded box, as Code's build log and Testing's
 * run transcript do. Deployment's Staging and Release transcripts had no bound,
 * so a live staging log stretched its stage to 3,053px of console.
 */
for (const [stage, section] of [
  ["Staging", "staging-console"],
  ["Release", "release-console"],
] as const) {
  test(`the ${stage} transcript is bounded and scrolls inside itself`, async ({ page }) => {
    await login(page);
    await page.goto("/projects/p4/deployment");
    await expect(page.locator("[data-stage-rail]")).toBeVisible({ timeout: 30_000 });
    // With the conversation open the rail condenses to one line, with no chevrons.
    const hide = page.getByRole("button", { name: /hide the conversation/i }).first();
    if (await hide.isVisible()) await hide.click();
    await page.locator("[data-stage-rail] .overflow-x-auto button", { hasText: stage }).click();
    const box = page.locator(`#${section} .tp-console`);
    await expect(box).toBeVisible();
    expect(await box.evaluate((el) => getComputedStyle(el).maxHeight)).toBe("420px");
  });
}

/**
 * A stage opens at its top. Moving on from the bottom of a long stage, with the
 * footer's Next or a chevron in the pinned rail, left the column where it was,
 * so the next stage opened scrolled to wherever the last one had been read to.
 */
async function openAtBottom(page: Page, phase: string) {
  await login(page);
  await page.goto(`/projects/p4/${phase}`);
  await expect(page.locator("[data-stage-rail]")).toBeVisible({ timeout: 30_000 });
  const hide = page.getByRole("button", { name: /hide the conversation/i }).first();
  if (await hide.isVisible()) await hide.click();
  const scrolled = await page.evaluate(() => {
    const scroller = document.querySelector("[data-stage-scroller]") as HTMLElement;
    scroller.scrollTop = scroller.scrollHeight;
    return scroller.scrollTop;
  });
  expect(scrolled).toBeGreaterThan(300);
}

/** How far the stage's top sits below the pinned rail's bottom, in pixels. */
async function stageTopBelowRail(page: Page): Promise<number> {
  return page.evaluate(() => {
    const top = document.querySelector("[data-stage-top]") as HTMLElement;
    const rail = document.querySelector("[data-stage-rail]") as HTMLElement;
    return top.getBoundingClientRect().top - rail.getBoundingClientRect().bottom;
  });
}

for (const [phase, from, to] of [
  ["deployment", "Staging", "Rollback Plan"],
  ["testing", "Test Run", "Test Quality"],
] as const) {
  test(`in ${phase}, Next at the bottom of ${from} opens ${to} at its top`, async ({ page }) => {
    await login(page);
    await page.goto(`/projects/p4/${phase}`);
    await expect(page.locator("[data-stage-rail]")).toBeVisible({ timeout: 30_000 });
    const hide = page.getByRole("button", { name: /hide the conversation/i }).first();
    if (await hide.isVisible()) await hide.click();
    await page.locator("[data-stage-rail] .overflow-x-auto button", { hasText: from }).click();
    await openAtBottomOfCurrent(page);

    await page.getByRole("button", { name: new RegExp(`Next\\s*${to}`) }).click();

    await expect(page.locator('[aria-current="step"]').first()).toHaveText(new RegExp(to));
    await expect.poll(() => stageTopBelowRail(page)).toBeGreaterThanOrEqual(0);
    expect(await stageTopBelowRail(page)).toBeLessThanOrEqual(40);
  });
}

test("a chevron in the pinned rail opens its stage at its top", async ({ page }) => {
  await openAtBottom(page, "deployment");
  await page.locator("[data-stage-rail] .overflow-x-auto button", { hasText: "Changelog Analysis" }).click();
  await expect.poll(() => stageTopBelowRail(page)).toBeGreaterThanOrEqual(0);
  expect(await stageTopBelowRail(page)).toBeLessThanOrEqual(40);
});

async function openAtBottomOfCurrent(page: Page) {
  const scrolled = await page.evaluate(() => {
    const scroller = document.querySelector("[data-stage-scroller]") as HTMLElement;
    scroller.scrollTop = scroller.scrollHeight;
    return scroller.scrollTop;
  });
  expect(scrolled).toBeGreaterThan(300);
}

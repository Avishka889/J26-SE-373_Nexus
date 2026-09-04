import { test, expect, type Page } from "@playwright/test";

/**
 * Nothing scrolls sideways at phone and tablet widths.
 *
 * The chevron row carries its own overflow-x-auto, but it sat in the rail as a
 * flex item with the default min-width:auto, so it refused to shrink below its
 * intrinsic 1167px: the row never scrolled inside itself and the stage column
 * scrolled horizontally instead, clipping the decision bar and cutting cards off
 * at the left. This regressed silently because no check ran at these widths.
 */
async function login(page: Page) {
  await page.goto("/login");
  await page.getByLabel(/email/i).fill("alex@acme.dev");
  await page.getByLabel(/password/i).fill("demo");
  await page.getByRole("button", { name: /log in/i }).click();
  await expect(page).toHaveURL(/\/workspace/);
}

/**
 * The sheet must start closed: it used to share the desktop panel's persisted
 * open state and covered the work on first paint. Asserted, not dismissed, so a
 * regression fails here rather than being silently worked around.
 */
async function expectTheSheetClosed(page: Page) {
  await expect(
    page.getByRole("button", { name: /close the conversation/i }),
  ).toHaveCount(0);
  await expect(page.getByRole("button", { name: /^Conversation/ })).toBeVisible();
}

for (const width of [390, 768]) {
  test.describe(`at ${width} wide`, () => {
    test.use({ viewport: { width, height: 900 } });

    for (const phase of [
      { name: "design", url: "/projects/p3/requirements", stages: 8 },
      // MediTrack is the project in `code`, so every code stage has content to
      // overflow with. A phase with nothing generated cannot scroll sideways
      // and would pass this sweep by having nothing in it.
      { name: "code", url: "/projects/p2/code", stages: 8 },
      // NotifyHub is past the test gate, so every testing stage has content to
      // overflow with. This phase could not be swept at all until it moved onto
      // the shared chrome: it rendered its own stepper and no `data-stage-rail`,
      // so the loop below had nothing to drive.
      { name: "testing", url: "/projects/p4/testing", stages: 7 },
      // NotifyHub again: past the test gate, with a review waiting and a
      // release down, so every deployment stage has content to overflow with.
      { name: "deployment", url: "/projects/p4/deployment", stages: 10 },
    ]) {
      test(`no ${phase.name} stage scrolls sideways`, async ({ page }) => {
      await login(page);
      await page.goto(phase.url);
      // A first load, as the other specs give one: four phases open at once on a
      // fresh development server, and a page still compiling missed five seconds
      // in one run of four, then in most runs of this spec alone, with or
      // without the change under test.
      await expect(page.locator("[data-stage-rail]")).toBeVisible({ timeout: 30_000 });
      await expectTheSheetClosed(page);

      const seen: {
        stage: string;
        body: boolean;
        column: boolean;
        columnScroll: number;
        columnClient: number;
      }[] = [];

      // Driven by the chevrons themselves: with the conversation dismissed the
      // rail shows the full row, which has no next arrow.
      const steps = page.locator("[data-stage-rail] .overflow-x-auto button");
      const total = await steps.count();

      for (let i = 0; i < total; i += 1) {
        await steps.nth(i).click();
        await page.waitForTimeout(600);
        seen.push(
          await page.evaluate(() => {
            const doc = document.scrollingElement as HTMLElement;
            const sc = document.querySelector(
              "[data-stage-scroller]",
            ) as HTMLElement;
            const label =
              document
                .querySelector('[aria-current="step"]')
                ?.textContent?.trim() ?? "unknown";
            return {
              stage: label.slice(0, 30),
              body: doc.scrollWidth > doc.clientWidth + 1,
              column: sc.scrollWidth > sc.clientWidth + 1,
              columnScroll: sc.scrollWidth,
              columnClient: sc.clientWidth,
            };
          }),
        );
      }

      // Without this the whole sweep could collapse to one stage and the rest
      // would pass by never having been looked at.
      // The phase's own count, not a constant. The two phases this started with
      // both have eight stages, so a literal passed for years and then failed
      // the day a seven stage phase joined the sweep, on the count rather than
      // on anything scrolling.
      expect(seen.length).toBe(phase.stages);
      expect(new Set(seen.map((r) => r.stage)).size).toBe(phase.stages);
      for (const row of seen) {
        expect(row.body, `the page scrolls sideways on ${row.stage}`).toBe(
          false,
        );
        expect(
          row.column,
          `the stage column scrolls sideways on ${row.stage} (${row.columnScroll} in ${row.columnClient})`,
        ).toBe(false);
      }
      });
    }

    test("the conversation is a toggle and the column takes the width", async ({
      page,
    }) => {
      await login(page);
      await page.goto("/projects/p3/requirements");
      await page.getByRole("button", { name: /request changes/i }).waitFor({
        timeout: 25000,
      });
      await expectTheSheetClosed(page);

      const seen = await page.evaluate(() => {
        const aside = document.querySelector(
          'aside[aria-label="Conversation"]',
        );
        const sheet = document.querySelector(".fixed.inset-0.z-40");
        const sc = document.querySelector(
          "[data-stage-scroller]",
        ) as HTMLElement;
        const toggle = Array.from(document.querySelectorAll("button")).find(
          (b) => /^Conversation/.test((b.textContent ?? "").trim()),
        );
        return {
          asideWidth: aside
            ? Math.round(aside.getBoundingClientRect().width)
            : 0,
          sheetOpen: sheet !== null,
          toggleVisible: toggle
            ? toggle.getBoundingClientRect().width > 0
            : false,
          columnWidth: Math.round(sc.getBoundingClientRect().width),
          shellWidth: Math.round(
            (
              document.querySelector("main") as HTMLElement
            ).getBoundingClientRect().width,
          ),
        };
      });

      // The desk column is gone and the sheet is dismissed: a toggle is the way back.
      expect(seen.asideWidth).toBe(0);
      expect(seen.sheetOpen).toBe(false);
      expect(seen.toggleVisible).toBe(true);
      // And the stage column has the whole of the shell to itself.
      expect(seen.columnWidth).toBe(seen.shellWidth);
    });
  });
}

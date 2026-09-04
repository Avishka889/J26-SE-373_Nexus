import { test, expect, type Page } from "@playwright/test";
import AxeBuilder from "@axe-core/playwright";

/**
 * Every page, every stage of every phase, each settings tab and the dialogs,
 * in both themes: no WCAG 2.1 A or AA violation that axe can find.
 *
 * Found by hand first: unnamed buttons on every page, muted text at 2.6:1, white
 * on amber chevrons at 1.7:1, a sign-in card whose labels followed the dark
 * theme onto white, cards a keyboard could not open, and a code view a keyboard
 * could not scroll. A sweep, so the next one is found here and not by a reader.
 * Automated checks find what they can find; they do not prove a page usable.
 */
const TAGS = ["wcag2a", "wcag2aa", "wcag21a", "wcag21aa"];

async function login(page: Page) {
  await page.goto("/login");
  await page.getByLabel(/email/i).fill("alex@acme.dev");
  await page.getByLabel(/password/i).fill("demo");
  await page.getByRole("button", { name: /log in/i }).click();
  await expect(page).toHaveURL(/\/workspace/);
}

async function expectAccessible(page: Page, where: string) {
  const { violations } = await new AxeBuilder({ page }).withTags(TAGS).analyze();
  const found = violations.map(
    (v) => `${v.id} (${v.impact}): ${v.nodes.slice(0, 3).map((n) => n.target.join(" ")).join(" | ")}`,
  );
  expect.soft(found, where).toEqual([]);
}

const PHASES = [
  { url: "/projects/p3/requirements", stages: 8 },
  { url: "/projects/p2/code", stages: 8 },
  { url: "/projects/p4/testing", stages: 7 },
  { url: "/projects/p4/deployment", stages: 10 },
];

for (const theme of ["light", "dark"] as const) {
  test.describe(`in the ${theme} theme`, () => {
    test.use({ viewport: { width: 1440, height: 900 } });
    test.beforeEach(async ({ page }) => {
      await page.addInitScript((chosen) => localStorage.setItem("sdlc-theme", chosen), theme);
    });

    test("the pages before signing in", async ({ page }) => {
      for (const url of ["/", "/login", "/register"]) {
        await page.goto(url);
        await page.waitForTimeout(800);
        await expectAccessible(page, url);
      }
    });

    test("the workspace, the projects, the activity log and the palette", async ({ page }) => {
      test.setTimeout(120_000);
      await login(page);
      for (const url of ["/workspace", "/projects", "/projects/p4/traceability"]) {
        await page.goto(url);
        await page.waitForTimeout(1500);
        await expectAccessible(page, url);
      }

      await page.goto("/projects");
      await page.getByRole("button", { name: "Show as a list" }).click();
      await expectAccessible(page, "the projects as a list");

      await page.getByRole("button", { name: /^Delete / }).first().click();
      await expect(page.getByRole("alertdialog")).toBeVisible();
      await expectAccessible(page, "the delete confirmation");
      await page.keyboard.press("Escape");

      await page.keyboard.press("Control+k");
      await expect(page.getByRole("dialog", { name: "Search projects and pages" })).toBeVisible();
      await expectAccessible(page, "the command palette");
    });

    test("every settings tab", async ({ page }) => {
      test.setTimeout(120_000);
      await login(page);
      await page.goto("/settings");
      await expect(page.getByRole("tablist", { name: "Settings sections" })).toBeVisible();
      const tabs = page.getByRole("tab");
      const total = await tabs.count();
      expect(total).toBeGreaterThan(1);
      for (let i = 0; i < total; i += 1) {
        await tabs.nth(i).click();
        await page.waitForTimeout(400);
        await expectAccessible(page, `settings tab ${i + 1}`);
      }
    });

    for (const phase of PHASES) {
      test(`every stage of ${phase.url}`, async ({ page }) => {
        test.setTimeout(240_000);
        await login(page);
        await page.goto(phase.url);
        await expect(page.locator("[data-stage-rail]")).toBeVisible({ timeout: 30_000 });
        // With the conversation open the rail shows the stage it is on, not the
        // whole row; closed, every chevron is there to step through.
        const hide = page.getByRole("button", { name: /hide the conversation/i });
        if (await hide.isVisible()) await hide.click();
        const steps = page.locator("[data-stage-rail] .overflow-x-auto button");
        await expect(steps).toHaveCount(phase.stages);
        for (let i = 0; i < phase.stages; i += 1) {
          if (await steps.nth(i).isDisabled()) continue;
          await steps.nth(i).click();
          await page.waitForTimeout(500);
          const stage = (await page.locator('[aria-current="step"]').textContent())?.trim() ?? `stage ${i + 1}`;
          await expectAccessible(page, `${phase.url}, ${stage}`);
        }
      });
    }
  });
}

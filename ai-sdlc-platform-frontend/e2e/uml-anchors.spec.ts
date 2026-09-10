import { test, expect, type Page } from "@playwright/test";

/**
 * The section pills on the UML stage must land on the cards they name.
 *
 * One grid held every diagram, so Behaviour scrolled to the top of a section
 * whose first card is the class diagram: the sequence diagram stayed 700px below
 * the fold and the spy lit Structure again. Measured against the stage column,
 * which is the scroller, rather than the window.
 */
async function login(page: Page) {
  await page.goto("/login");
  await page.getByLabel(/email/i).fill("alex@acme.dev");
  await page.getByLabel(/password/i).fill("demo");
  await page.getByRole("button", { name: /log in/i }).click();
  await expect(page).toHaveURL(/\/workspace/);
}

test.use({ viewport: { width: 1440, height: 900 } });

test.describe("the UML section pills", () => {
  test.beforeEach(async ({ page }) => {
    await login(page);
    await page.goto("/projects/p3/requirements");
    await page
      .getByRole("button", { name: /uml.?diagrams/i })
      .first()
      .click();
    // The reported case is with the conversation taking its share of the width.
    await expect(
      page.getByRole("button", { name: /hide the conversation/i }),
    ).toBeVisible();
    // Mermaid renders to real svg, and the cards above the target must have
    // their final height before an anchor offset means anything. The id prefix
    // matters: a bare svg selector matched a chevron icon in the rail, which
    // made this wait vacuous, and the rail now renders a hidden sibling tree
    // whose icons would satisfy or break it for the wrong reasons either way.
    await expect(
      page.locator('[data-stage-scroller] svg[id^="mermaid"]').first(),
    ).toBeVisible({ timeout: 20000 });
    await page.waitForTimeout(1200);
  });

  test("Behaviour brings the sequence diagram into view", async ({ page }) => {
    await page.getByRole("button", { name: "Behaviour", exact: true }).click();
    await page.waitForTimeout(1500); // smooth scroll

    const seen = await page.evaluate(() => {
      const sc = document.querySelector("[data-stage-scroller]") as HTMLElement;
      const box = sc.getBoundingClientRect();
      const card = Array.from(
        document.querySelectorAll("[data-stage-scroller] h3"),
      ).find((h) => /sequence diagram/i.test(h.textContent ?? ""));
      const section = document.getElementById("uml-behaviour");
      const active = document.querySelector('[aria-current="location"]');
      const rel = (el: Element | null | undefined) =>
        el ? Math.round(el.getBoundingClientRect().top - box.top) : null;
      return {
        sectionTop: rel(section),
        cardTop: rel(card),
        viewportHeight: Math.round(box.height),
        activePill: (active?.textContent ?? "").trim(),
      };
    });

    // Guards: a missing card or a zero height scroller would make the rest pass
    // for the wrong reason.
    expect(seen.cardTop).not.toBeNull();
    expect(seen.viewportHeight).toBeGreaterThan(300);

    // The section it names lands at the top of the column, under the rail.
    expect(seen.sectionTop!).toBeGreaterThanOrEqual(0);
    expect(seen.sectionTop!).toBeLessThan(200);
    // And the sequence diagram is actually on screen, which is the point.
    expect(seen.cardTop!).toBeGreaterThanOrEqual(0);
    expect(seen.cardTop!).toBeLessThan(seen.viewportHeight);
    // The pill that was clicked is the pill that lights.
    expect(seen.activePill).toBe("Behaviour");
  });

  test("each section holds the diagrams it names", async ({ page }) => {
    // The heights of the fixture diagrams happen to keep the sequence card on
    // screen even when every card shares one section, so "is it visible" alone
    // would not catch the split being undone. This asserts the split itself.
    const titles = await page.evaluate(() => {
      const of = (id: string) =>
        Array.from(document.querySelectorAll(`#${id} h3`))
          .map((h) => (h.textContent ?? "").trim())
          .filter(Boolean);
      return { structure: of("uml-structure"), behaviour: of("uml-behaviour") };
    });

    expect(titles.structure.length).toBeGreaterThan(0);
    expect(titles.behaviour.length).toBeGreaterThan(0);
    expect(titles.structure.join(" | ")).toMatch(/class diagram/i);
    expect(titles.behaviour.join(" | ")).toMatch(/sequence diagram/i);
    // The structural diagrams must not be sitting under the Behaviour pill,
    // which is exactly what made it scroll to the wrong card.
    expect(titles.behaviour.join(" | ")).not.toMatch(
      /class diagram|entity relationship/i,
    );
  });

  test("Structure brings the class diagram into view", async ({ page }) => {
    await page.getByRole("button", { name: "Structure", exact: true }).click();
    await page.waitForTimeout(1500);

    const seen = await page.evaluate(() => {
      const sc = document.querySelector("[data-stage-scroller]") as HTMLElement;
      const box = sc.getBoundingClientRect();
      const card = Array.from(
        document.querySelectorAll("[data-stage-scroller] h3"),
      ).find((h) => /class diagram/i.test(h.textContent ?? ""));
      return {
        cardTop: card
          ? Math.round(card.getBoundingClientRect().top - box.top)
          : null,
        viewportHeight: Math.round(box.height),
        activePill: (
          document.querySelector('[aria-current="location"]')?.textContent ?? ""
        ).trim(),
      };
    });

    expect(seen.cardTop).not.toBeNull();
    expect(seen.cardTop!).toBeGreaterThanOrEqual(0);
    expect(seen.cardTop!).toBeLessThan(seen.viewportHeight);
    expect(seen.activePill).toBe("Structure");
  });
});

import { test, expect, type Page } from "@playwright/test";

/**
 * The send button must be reachable without scrolling the page.
 *
 * The panel is a sticky element whose height matches the viewport, but at scroll
 * 0 it sits at its in-flow position well below the top, so its last child, the
 * composer, hung below the fold until the page was scrolled. Measured rather
 * than eyeballed, because two attempts at this were fixed by guessing at a pixel
 * height and both were wrong.
 */

async function login(page: Page) {
  await page.goto("/login");
  await page.getByLabel(/email/i).fill("alex@acme.dev");
  await page.getByLabel(/password/i).fill("demo");
  await page.getByRole("button", { name: /log in/i }).click();
  await expect(page).toHaveURL(/\/workspace/);
}

const WIDTHS = [1440, 1905];
const SCROLLS = ["top", "300", "bottom"] as const;

for (const width of WIDTHS) {
  test.describe(`at ${width} wide`, () => {
    test.use({ viewport: { width, height: 900 } });

    for (const where of SCROLLS) {
      test(`the send button is inside the viewport at scroll ${where}`, async ({
        page,
      }) => {
        await login(page);
        await page.goto("/projects/p3/requirements");
        await page
          .locator('button[aria-label="Send"]')
          .first()
          .waitFor({ timeout: 20000 });

        // The stage column is the scrollport, not the document and no longer
        // main. Scrolling the window here did nothing and made two of the three
        // conditions vacuous.
        // Set the scroll and read the geometry in one pass. Split across two
        // evaluates the offset came back as 0 every time, so the check reported
        // three scroll positions while measuring one.
        const seen = await page.evaluate((target) => {
          // Whichever element actually scrolls the stage content: the column
          // after this change, <main> before it. Naming only the new one made a
          // revert fail on the selector, which proves nothing about the
          // assertions.
          const column = (document.querySelector("[data-stage-scroller]") ??
            document.querySelector("main")) as HTMLElement | null;
          if (!column) throw new Error("no scrollport found at all");
          if (target === "top") column.scrollTop = 0;
          else if (target === "bottom") column.scrollTop = column.scrollHeight;
          else column.scrollTop = Number(target);
          // Read back after the write so the value is the one the browser kept.
          const scrollTop = Math.round(column.scrollTop);

          const send = document.querySelector('button[aria-label="Send"]');
          const list = document.querySelector(
            'aside[aria-label="Conversation"] ol',
          );
          const composer =
            send?.closest("div")?.parentElement?.parentElement ?? null;
          const box = send?.getBoundingClientRect();
          return box
            ? {
                top: Math.round(box.top),
                bottom: Math.round(box.bottom),
                viewport: window.innerHeight,
                scrollTop,
                columnScrollHeight: column.scrollHeight,
                lastMessageBottom: list?.lastElementChild
                  ? Math.round(
                      list.lastElementChild.getBoundingClientRect().bottom,
                    )
                  : null,
                composerTop: composer
                  ? Math.round(composer.getBoundingClientRect().top)
                  : null,
              }
            : null;
        }, where);

        console.log(`MEASURED ${width} ${where} ${JSON.stringify(seen)}`);
        expect(seen).not.toBeNull();
        expect(seen!.bottom).toBeLessThanOrEqual(seen!.viewport);
        expect(seen!.top).toBeGreaterThanOrEqual(0);
        // The composer must never cover the newest message.
        expect(seen!.lastMessageBottom!).toBeLessThanOrEqual(
          seen!.composerTop!,
        );
        // And the column must genuinely be at the offset this case names.
        if (where === "300") expect(seen!.scrollTop).toBe(300);
        if (where === "bottom") expect(seen!.scrollTop).toBeGreaterThan(0);
      });
    }
  });
}

test.describe("the transcript keeps its scrolling to itself", () => {
  test.use({ viewport: { width: 1440, height: 900 } });

  test("reaching the end of the transcript does not move the page", async ({
    page,
  }) => {
    // Scroll chaining: at the foot of the transcript the wheel was handed to
    // the column beside it, which dragged the design out of view mid-read.
    await login(page);
    await page.goto("/projects/p3/requirements");
    await page
      .locator('button[aria-label="Send"]')
      .first()
      .waitFor({ timeout: 20000 });

    const transcript = page
      .locator('aside[aria-label="Conversation"] ol')
      .first();
    await transcript.waitFor();

    const before = await page.evaluate(() => {
      const main = (document.querySelector("[data-stage-scroller]") ??
        document.querySelector("main")) as HTMLElement;
      main.scrollTop = 400;
      const list = document.querySelector(
        "ol.overscroll-contain",
      ) as HTMLElement;
      list.scrollTop = list.scrollHeight;
      return {
        main: Math.round(main.scrollTop),
        list: Math.round(list.scrollTop),
      };
    });

    // Keep wheeling once the transcript has nothing left to give.
    const box = await transcript.boundingBox();
    await page.mouse.move(box!.x + box!.width / 2, box!.y + box!.height / 2);
    for (let i = 0; i < 6; i += 1) await page.mouse.wheel(0, 200);
    await page.waitForTimeout(400);

    const after = await page.evaluate(() => ({
      main: Math.round(
        (document.querySelector("[data-stage-scroller]") ??
          document.querySelector("main"))!.scrollTop,
      ),
    }));

    console.log(
      `CHAINING before=${JSON.stringify(before)} after=${JSON.stringify(after)}`,
    );
    expect(after.main).toBe(before.main);
  });
});

/**
 * What moved when the scrollport did.
 *
 * Every sticky and scroll behaviour in this phase was written against <main>.
 * The stage column is the scroller now, so each of them is worth reading back
 * rather than assuming it survived.
 */
test.describe("the phase still behaves with the column as scroller", () => {
  test.use({ viewport: { width: 1440, height: 900 } });

  test.beforeEach(async ({ page }) => {
    await login(page);
    await page.goto("/projects/p3/requirements");
    await page
      .locator('button[aria-label="Send"]')
      .first()
      .waitFor({ timeout: 20000 });
    await page.waitForTimeout(600);
  });

  test("the stage rail sticks to the top of the column, with no gap", async ({
    page,
  }) => {
    const seen = await page.evaluate(() => {
      const column = document.querySelector(
        "[data-stage-scroller]",
      ) as HTMLElement;
      column.scrollTop = 600;
      const rail = document.querySelector(
        "[data-stage-rail]",
      ) as HTMLElement | null;
      return {
        columnTop: Math.round(column.getBoundingClientRect().top),
        railTop: rail ? Math.round(rail.getBoundingClientRect().top) : null,
      };
    });
    // Sticking at top 0 of the column: any gap means it is still offsetting by
    // a tab bar that is no longer inside the scroller.
    expect(seen.railTop).not.toBeNull();
    expect(Math.abs(seen.railTop! - seen.columnTop)).toBeLessThanOrEqual(2);
  });

  test("an anchor jump scrolls the column and lands clear of the rail", async ({
    page,
  }) => {
    const seen = await page.evaluate(async () => {
      const column = document.querySelector(
        "[data-stage-scroller]",
      ) as HTMLElement;
      const before = column.scrollTop;
      const anchor = document.querySelector(".tp-anchor") as HTMLElement | null;
      anchor?.scrollIntoView({ block: "start" });
      await new Promise((r) => setTimeout(r, 400));
      const rail = document.querySelector(
        "[data-stage-rail]",
      ) as HTMLElement | null;
      return {
        moved: column.scrollTop !== before || before === 0,
        anchorTop: anchor
          ? Math.round(anchor.getBoundingClientRect().top)
          : null,
        railBottom: rail
          ? Math.round(rail.getBoundingClientRect().bottom)
          : null,
        mainScrollTop: Math.round(document.querySelector("main")!.scrollTop),
      };
    });
    // The page itself must not move: only the column scrolls now.
    expect(seen.mainScrollTop).toBe(0);
    // And the section must not land underneath the rail that covers it.
    if (seen.anchorTop !== null && seen.railBottom !== null) {
      expect(seen.anchorTop).toBeGreaterThanOrEqual(seen.railBottom - 4);
    }
  });

  test("the decision bar stays put while the column scrolls", async ({
    page,
  }) => {
    // A project with all eight stages complete and its gate still open: the bar
    // does not render once a decision is recorded, and the project the other
    // checks use has been approved.
    await page.goto("/projects/p3/requirements");
    await page
      .getByRole("button", { name: /request changes/i })
      .waitFor({ timeout: 20000 });

    const seen = await page.evaluate(() => {
      const column = document.querySelector(
        "[data-stage-scroller]",
      ) as HTMLElement;
      // The button itself, rather than an ancestor guessed at by class name.
      const bar = Array.from(document.querySelectorAll("button")).find((b) =>
        /request changes/i.test(b.textContent ?? ""),
      );
      const at = (t: number) => {
        column.scrollTop = t;
        const r = bar?.getBoundingClientRect();
        return r ? Math.round(r.top) : null;
      };
      return { top: at(0), scrolled: at(900), viewport: window.innerHeight };
    });

    expect(seen.top).not.toBeNull();
    // Anchored to the viewport: scrolling the column must not move it.
    expect(seen.scrolled).toBe(seen.top);
    expect(seen.top!).toBeLessThan(seen.viewport);
  });

  test("with the conversation closed the column still fills the row", async ({
    page,
  }) => {
    await page.getByRole("button", { name: /hide the conversation/i }).click();
    await page.waitForTimeout(300);
    const seen = await page.evaluate(() => {
      const column = document.querySelector(
        "[data-stage-scroller]",
      ) as HTMLElement;
      const r = column.getBoundingClientRect();
      return {
        bottom: Math.round(r.bottom),
        viewport: window.innerHeight,
        scrolls: column.scrollHeight > column.clientHeight,
        mainScrolls: (() => {
          const m = document.querySelector("main")!;
          return m.scrollHeight > m.clientHeight + 4;
        })(),
      };
    });
    expect(seen.bottom).toBeLessThanOrEqual(seen.viewport);
    expect(seen.scrolls).toBe(true);
    expect(seen.mainScrolls).toBe(false);
  });

  test("stepping through the stages never hands <main> a scrollbar", async ({
    page,
  }) => {
    // sr-only spans inside the stages are position:absolute. With no positioned
    // ancestor between them and the app shell root, the root became their
    // containing block, its scrollHeight grew to the whole stage list, and the
    // first stage click scrolled the project header and phase tabs off the top.
    const read = () =>
      page.evaluate(() => {
        const main = document.querySelector("main")!;
        const tab = Array.from(document.querySelectorAll("a,button")).find(
          (e) => /^Code Generation$/i.test((e.textContent ?? "").trim()),
        );
        return {
          scrolls: main.scrollHeight > main.clientHeight + 4,
          scrollTop: main.scrollTop,
          tabTop: tab ? Math.round(tab.getBoundingClientRect().top) : null,
        };
      });

    const before = await read();
    // Without this the whole check passes on a page that never rendered.
    expect(before.tabTop).not.toBeNull();
    expect(before.scrolls).toBe(false);

    const next = page.locator('button[aria-label^="Next:"]');
    let stepped = 0;
    for (let i = 0; i < 6; i += 1) {
      if (!(await next.isEnabled().catch(() => false))) break;
      await next.click();
      await page.waitForTimeout(400);
      stepped += 1;
    }
    // The bug needs a later, taller stage to show itself.
    expect(stepped).toBeGreaterThanOrEqual(3);

    const after = await read();
    expect(after.scrolls).toBe(false);
    expect(after.scrollTop).toBe(0);
    expect(after.tabTop).toBe(before.tabTop);
  });
});

/**
 * The decision bar at a width where the conversation column takes half the row.
 *
 * `lg:flex-row` is a viewport breakpoint answering a container question: at 1100
 * the row goes horizontal because the window is wide, but the stage column is
 * not, so the two shrink-0 buttons starved the headline to 49px and it rendered
 * five words tall. Measured, because jsdom cannot see a line box.
 */
test.describe("the decision bar headline survives a narrow column", () => {
  test.use({ viewport: { width: 1100, height: 900 } });

  test("the headline stays on one line with the conversation open", async ({
    page,
  }) => {
    await login(page);
    await page.goto("/projects/p3/requirements");
    await page
      .getByRole("button", { name: /request changes/i })
      .waitFor({ timeout: 20000 });
    // The conversation opens by default; assert that rather than assume it, so
    // this does not quietly become the easy, wide case.
    await expect(
      page.getByRole("button", { name: /hide the conversation/i }),
    ).toBeVisible();

    const seen = await page.evaluate(() => {
      const bar = Array.from(document.querySelectorAll("div.sticky")).find(
        (b) => /waiting on you/.test(b.textContent ?? ""),
      );
      const head = bar?.querySelector("p.font-semibold") as HTMLElement | null;
      if (!head) return null;
      const lineHeight = parseFloat(getComputedStyle(head).lineHeight) || 18;
      const box = head.getBoundingClientRect();
      const range = document.createRange();
      range.selectNodeContents(head);
      const actions = Array.from(bar!.querySelectorAll("button"))
        .filter((b) => /request changes|approve/i.test(b.textContent ?? ""))
        .map((b) => {
          const r = b.getBoundingClientRect();
          return { top: Math.round(r.top), width: Math.round(r.width) };
        });
      return {
        lines: Math.round(box.height / lineHeight),
        boxWidth: Math.round(box.width),
        textWidth: Math.round(range.getBoundingClientRect().width),
        actions,
      };
    });

    expect(seen).not.toBeNull();
    // The text has room for itself, so it occupies exactly one line box.
    expect(seen!.boxWidth).toBeGreaterThanOrEqual(seen!.textWidth);
    expect(seen!.lines).toBe(1);
    // The buttons wrap as a unit onto their own row: still two of them, still
    // side by side, still wide enough to read. That is what buys the headline
    // its width, so it is the other half of the same assertion.
    expect(seen!.actions).toHaveLength(2);
    expect(seen!.actions[0].top).toBe(seen!.actions[1].top);
    for (const a of seen!.actions) expect(a.width).toBeGreaterThan(100);
  });

  test("a panel header keeps its title when the action is wide", async ({
    page,
  }) => {
    await login(page);
    await page.goto("/projects/p3/requirements");
    await page
      .getByRole("button", { name: /request changes/i })
      .waitFor({ timeout: 25000 });
    await expect(
      page.getByRole("button", { name: /hide the conversation/i }),
    ).toBeVisible();

    // The UML cards carry the widest actions in the app: a use case select, a
    // Diagram/Source toggle and an expand control. jsdom cannot see a line box,
    // so this measures the title block, which is the thing that used to collapse
    // to one word per line.
    // The rail is condensed while the conversation holds its share of the
    // width, so there is no chevron to click: step with the next arrow.
    for (let i = 0; i < 8; i += 1) {
      // Keyed on the rail's stage name: the graph stage's prose mentions a
      // class diagram, so matching the column text stopped three stages early.
      // The selected chevron, not the rail's whole text: the rail renders a
      // hidden sibling tree naming every stage, so its textContent always
      // contains "UML Diagrams" and matching it broke the loop on stage one.
      const stage = await page.evaluate(
        () =>
          document.querySelector('[data-stage-rail] [aria-current="step"]')
            ?.textContent ?? "",
      );
      if (/uml diagrams/i.test(stage)) break;
      const next = page.locator('button[aria-label^="Next:"]');
      if (!(await next.isEnabled({ timeout: 3000 }).catch(() => false))) break;
      await next.click();
      await page.waitForTimeout(500);
    }
    const reached = await page.evaluate(
      () => document.querySelector("[data-stage-scroller]")?.textContent ?? "",
    );
    expect(reached).toMatch(/sequence diagram/i);
    await page.waitForTimeout(1200);

    const seen = await page.evaluate(() => {
      const sc = document.querySelector("[data-stage-scroller]") as HTMLElement;
      // Found through the diagram headings rather than through the layout class
      // under test: keying on .basis-64 would make removing it empty the list
      // and the assertions below would pass on nothing.
      const rows = Array.from(sc.querySelectorAll("h3"))
        .filter((h) => /diagram/i.test(h.textContent ?? ""))
        .map((h) => h.closest("div.flex.flex-wrap"))
        .filter((row): row is HTMLElement => row !== null);

      return {
        columnOverflowsX: sc.scrollWidth > sc.clientWidth + 1,
        headers: rows.map((row) => {
          const title = row.children[0] as HTMLElement;
          const action = row.children[1] as HTMLElement | undefined;
          const t = title.getBoundingClientRect();
          return {
            titleWidth: Math.round(t.width),
            hasAction: action !== undefined,
            actionOnOwnLine: action
              ? Math.round(action.getBoundingClientRect().top) >
                Math.round(t.top)
              : null,
          };
        }),
      };
    });

    // Guard: no panels found would pass every assertion below.
    const withAction = seen.headers.filter((h) => h.hasAction);
    expect(withAction.length).toBeGreaterThan(0);
    expect(seen.columnOverflowsX).toBe(false);
    for (const h of seen.headers) {
      // Either the action moved to its own line, or the title kept real width.
      // What must never happen is a title crushed beside the action.
      expect(h.actionOnOwnLine || h.titleWidth >= 240).toBe(true);
    }
  });
});

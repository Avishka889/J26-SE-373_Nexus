import { test, expect, type Page } from "@playwright/test";

/**
 * The Requirements and Design phase, as a browser sees it.
 *
 * These assert the things a unit test cannot: that the sticky chrome sits where
 * it should, that a project's badge and its gate agree on screen rather than in a
 * fixture, and that nothing on the page contradicts anything else on the page.
 *
 * Screenshots go to the scratchpad so the rendering can be looked at rather than
 * inferred from assertions.
 */

const SHOTS = process.env.SHOT_DIR ?? "/tmp/shots";

/** The width the browser evaluation used, where the chevron row clipped. */
test.use({
  viewport: { width: 1440, height: 900 },
  // CHROME_PATH lets this run against a browser already on the machine, which is
  // what makes the review runnable without waiting on a fresh download.
  launchOptions: process.env.CHROME_PATH
    ? { executablePath: process.env.CHROME_PATH }
    : {},
});

async function login(page: Page) {
  await page.goto("/login");
  await page.getByLabel(/email/i).fill("alex@acme.dev");
  await page.getByLabel(/password/i).fill("demo");
  await page.getByRole("button", { name: /log in/i }).click();
  await expect(page).toHaveURL(/\/workspace/);
}

/** Anything the console complains about is a finding, not noise. */
function watchConsole(page: Page) {
  const problems: string[] = [];
  page.on("console", (message) => {
    const text = message.text();
    // The mock service worker logs this on a client side navigation. It is the
    // fixture layer talking about itself, not the app misbehaving.
    if (text.includes('redundant "worker.start()"')) return;
    // React Flow 11 reports this when StrictMode renders twice in development
    // and its store sees the nodeTypes object initialise twice. `graphNodeTypes`
    // is a module constant, and a production build's console is clean, which was
    // checked against `vite preview` rather than assumed.
    if (text.includes("new nodeTypes or edgeTypes object")) return;
    if (message.type() === "error" || message.type() === "warning") {
      problems.push(`${message.type()}: ${text}`);
    }
  });
  page.on("pageerror", (error) => problems.push(`pageerror: ${error.message}`));
  return problems;
}

test.describe("the design phase in a browser", () => {
  test.beforeEach(async ({ page }) => {
    await login(page);
  });

  test("ShopFlow is the one waiting on a decision", async ({ page }) => {
    const problems = watchConsole(page);
    await page.goto("/projects/p3/requirements");
    await page.waitForLoadState("networkidle");

    await page.screenshot({
      path: `${SHOTS}/01-shopflow-top.png`,
      fullPage: false,
    });

    // Its own domain, not payments.
    await expect(
      page.getByText(/cart|catalog|checkout/i).first(),
    ).toBeVisible();

    // The decision bar, which only this project should show.
    await expect(page.getByText(/waiting on you/i).first()).toBeVisible();

    // No stack chips: the stack is chosen in Code Generation.
    await expect(page.getByText(/React · Express · Redis · AWS/)).toHaveCount(
      0,
    );

    expect(problems, problems.join("\n")).toEqual([]);
  });

  test("NexusPay shows an approved gate, not a prompt", async ({ page }) => {
    const problems = watchConsole(page);
    await page.goto("/projects/p1/requirements");
    await page.waitForLoadState("networkidle");
    await page.screenshot({ path: `${SHOTS}/02-nexuspay-top.png` });

    // Past the gate, so no decision bar anywhere on the page.
    await expect(page.getByText(/waiting on you/i)).toHaveCount(0);
    await expect(page.getByText(/^Approved$/).first()).toBeVisible();

    // And no open questions to answer.
    await expect(page.getByText(/answer in chat/i)).toHaveCount(0);

    expect(problems, problems.join("\n")).toEqual([]);
  });

  test("the stage row sticks and condenses, and Design Review is never clipped", async ({
    page,
  }) => {
    await page.goto("/projects/p3/requirements");
    await page.waitForLoadState("networkidle");

    // The full row is the wide layout. With the panel open the condensed form is
    // mandatory, because eight chevrons do not fit beside it.
    await page.getByRole("button", { name: /hide the conversation/i }).click();
    await page.waitForTimeout(400);
    await expect(
      page.getByRole("button", { name: /Requirements Analysis/ }).first(),
    ).toBeVisible();
    await page.screenshot({ path: `${SHOTS}/03-nav-unstuck.png` });

    // Scroll the artifact. The row sticks, and with the conversation closed it
    // stays the full rail: condensing is about width, not about scrolling. It
    // used to swap here, and that swap changed the bar's height at the exact
    // scroll position that triggered it, which is what flickered.
    await page.mouse.wheel(0, 900);
    await page.waitForTimeout(600);
    await page.screenshot({ path: `${SHOTS}/04-nav-stuck.png` });

    await expect(
      page.getByRole("button", { name: /Requirements Analysis/ }).first(),
    ).toBeVisible();
    await expect(page.getByText(/Stage \d of 8/)).toHaveCount(0);

    // Opening the conversation is what condenses it, because eight chevrons do
    // not fit beside the panel.
    await page
      .getByRole("button", { name: /^Conversation/i })
      .first()
      .click();
    await page.waitForTimeout(400);
    await expect(page.getByText(/Stage \d of 8/)).toBeVisible();
    await page.getByRole("button", { name: /hide the conversation/i }).click();
    await page.waitForTimeout(400);

    // The gate stage must be reachable, which is what clipping broke.
    await page.mouse.wheel(0, -2000);
    await page.waitForTimeout(400);
    // Present, in view and usable. The row still scrolls horizontally, so the
    // last chevron can sit against the edge; what must never happen is the gate
    // stage being off the end where the reader cannot get to it.
    const review = page.getByRole("button", { name: /Design Review/ }).first();
    await expect(review).toBeVisible();
    await expect(review).toBeInViewport();
    await review.click();
    await page.waitForTimeout(600);
    // Its own anchors, which only exist when the review stage is the open one.
    // "Stage 8 of 8" belongs to the condensed form, and the panel is closed here.
    await expect(
      page.getByRole("button", { name: "Decision", exact: true }),
    ).toBeVisible();
    await page.screenshot({ path: `${SHOTS}/18-design-review-stage.png` });
  });

  test("section anchors scroll to their block", async ({ page }) => {
    await page.goto("/projects/p3/requirements");
    await page.waitForLoadState("networkidle");

    const anchor = page.getByRole("button", {
      name: "Assumptions",
      exact: true,
    });
    await expect(anchor).toBeVisible();
    await anchor.click();
    await page.waitForTimeout(900);

    const block = page.locator("#requirements-assumptions");
    await expect(block).toBeInViewport();
    await page.screenshot({ path: `${SHOTS}/05-anchor-assumptions.png` });
  });

  test("the requirements list is compact and filterable", async ({ page }) => {
    await page.goto("/projects/p3/requirements");
    await page.waitForLoadState("networkidle");
    await page.screenshot({ path: `${SHOTS}/06-requirements-compact.png` });

    // Twelve requirements should not be twelve screens.
    const rows = page.locator("#requirements-list li");
    await expect(rows).toHaveCount(12);

    await page.getByRole("button", { name: /needs attention/i }).click();
    await page.waitForTimeout(300);
    await expect(
      page.getByText(/showing \d+ of 12 requirements/i),
    ).toBeVisible();
    await page.screenshot({ path: `${SHOTS}/07-requirements-filtered.png` });

    // Nothing is concealed: clearing brings everything back.
    await page.getByRole("button", { name: /clear filters/i }).click();
    await page.waitForTimeout(300);
    await expect(rows).toHaveCount(12);

    // A row opens to the whole record.
    await rows.first().getByRole("button").first().click();
    await page.waitForTimeout(300);
    await page.screenshot({ path: `${SHOTS}/08-requirement-expanded.png` });
  });

  test("the conversation panel holds the input and the questions", async ({
    page,
  }) => {
    await page.goto("/projects/p3/requirements");
    await page.waitForLoadState("networkidle");

    // The reader's own words open the transcript.
    // By name: the app sidebar is an <aside> too, and it comes first in the DOM.
    const panel = page.getByRole("complementary", { name: "Conversation" });
    await expect(panel).toBeVisible();
    await expect(panel.getByText(/headless e-commerce/i)).toHaveCount(1);
    await page.screenshot({ path: `${SHOTS}/09-conversation.png` });

    // Questions are asked here, with the reply box in the bubble.
    await expect(
      panel.getByPlaceholder(/answer in a sentence/i).first(),
    ).toBeVisible();

    // And the stage carries a pointer rather than a second form.
    await expect(
      page.getByRole("button", { name: /answer in chat/i }).first(),
    ).toBeVisible();
  });

  test("clicking a graph node opens its detail in view", async ({ page }) => {
    await page.goto("/projects/p3/requirements");
    await page.waitForLoadState("networkidle");

    await page
      .getByRole("button", { name: /Architecture Graph/ })
      .first()
      .click();
    await page.waitForTimeout(900);
    await page.screenshot({ path: `${SHOTS}/10-graph.png` });

    const node = page.locator(".react-flow__node").first();
    await expect(node).toBeVisible();
    await node.click();
    await page.waitForTimeout(1200);

    await expect(page.locator("#graph-detail")).toBeInViewport();
    await page.screenshot({ path: `${SHOTS}/11-graph-node-detail.png` });
  });

  test("every stage ends in a way forward", async ({ page }) => {
    await page.goto("/projects/p3/requirements");
    await page.waitForLoadState("networkidle");

    const footerNext = page.getByRole("button", {
      name: /^Next Domain Model$/i,
    });
    await expect(footerNext).toBeVisible();
    await footerNext.click();
    await page.waitForTimeout(600);
    await expect(
      page.getByRole("button", { name: /^Next Architecture Graph$/i }),
    ).toBeVisible();
    await page.screenshot({ path: `${SHOTS}/12-next-footer.png` });
  });

  test("a new project generates one stage at a time", async ({ page }) => {
    const problems = watchConsole(page);
    await page.goto("/projects/new");
    await page.waitForLoadState("networkidle");

    await page
      .getByRole("textbox")
      .first()
      .fill("Build a simple calculator app");
    await page.keyboard.press("Enter");

    await page.waitForURL(/\/projects\/.*\/requirements/, { timeout: 15000 });
    await page.waitForTimeout(1500);
    await page.screenshot({ path: `${SHOTS}/13-new-project-generating.png` });

    // One generating indicator, and no decision offered yet.
    await expect(page.getByText(/^Generating /).first()).toBeVisible();
    await expect(page.getByText(/waiting on you/i)).toHaveCount(0);

    // Let the run finish.
    await page.waitForTimeout(13000);
    await page.screenshot({ path: `${SHOTS}/14-new-project-done.png` });
    await expect(page.getByText(/waiting on you/i).first()).toBeVisible();
    await expect(page.getByText(/^Generating /)).toHaveCount(0);

    expect(problems, problems.join("\n")).toEqual([]);
  });

  test("the other phases still render", async ({ page }) => {
    const problems = watchConsole(page);
    for (const [phase, shot] of [
      ["code-generation", "15-code"],
      ["testing", "16-testing"],
      ["deployment", "17-deployment"],
    ] as const) {
      await page.goto(`/projects/p1/${phase}`);
      await page.waitForLoadState("networkidle");
      await page.screenshot({ path: `${SHOTS}/${shot}.png` });
    }
    expect(problems, problems.join("\n")).toEqual([]);
  });
});

/** The gate stage, reached the way the working navigation test reaches it. */
test("continuing from an approved design lands on the code phase", async ({
  page,
}) => {
  /**
   * The button used to PATCH the project to status "code" with a progress
   * number. Both are derived from the runs and the gates now, so the server
   * dropped them and answered 200: a control that sent a request, changed
   * nothing and left the reader where they were.
   */
  await login(page);
  await page.goto("/projects/p2/requirements");
  await page.waitForLoadState("networkidle");
  await page.getByRole("button", { name: /hide the conversation/i }).click();
  await page.getByRole("button", { name: /Design Review/ }).first().click();
  await page.waitForTimeout(600);

  await page
    .getByRole("button", { name: /Continue to Code Generation/i })
    .click();

  await expect(page).toHaveURL(/\/projects\/p2\/code(\?.*)?$/);
  // The banner's heading: the phase renders its own inside main as well, and
  // an unscoped match is two elements rather than none.
  await expect(
    page.getByRole("banner").getByRole("heading", { name: "Code Generation" }),
  ).toBeVisible();
});

async function openDesignReview(page: Page) {
  await page.goto("/projects/p3/requirements");
  await page.waitForLoadState("networkidle");
  // The full chevron row only exists with the conversation hidden; condensed,
  // there is no Design Review button to click.
  await page.getByRole("button", { name: /hide the conversation/i }).click();
  await page.waitForTimeout(400);
  await page
    .getByRole("button", { name: /Design Review/ })
    .first()
    .click();
  await page.waitForTimeout(600);
}

test.describe("cross artifact findings at the gate", () => {
  test.beforeEach(async ({ page }) => {
    await login(page);
  });

  test("the disagreement panel is on the page a decision is made on", async ({
    page,
  }) => {
    await openDesignReview(page);

    // The whole reason this panel exists: none of these can be seen from inside
    // the stage they concern, and this is where somebody decides.
    const panel = page.getByText("These artifacts disagree");
    await expect(panel).toBeVisible();

    const findings = page.getByText(/has no screen in any journey/);
    expect(await findings.count()).toBeGreaterThan(0);
    await expect(findings.first()).toBeVisible();

    // It informs, it does not block: the decision controls are still usable.
    await expect(
      page.getByRole("button", { name: "Decision", exact: true }),
    ).toBeVisible();

    // The artifact area is its own scroll container, so the wheel is what moves
    // it. scrollIntoViewIfNeeded does not reach inside it.
    await page.mouse.move(800, 600);
    await page.mouse.wheel(0, 700);
    await page.waitForTimeout(400);
    await page.screenshot({ path: `${SHOTS}/19-consistency-panel.png` });
  });

  test("a finding sends the reader to the stage that would fix it", async ({
    page,
  }) => {
    await openDesignReview(page);

    // Scoped to the finding's own row. "Open Wireframes" also appears on the
    // Design artifacts card, and clicking that one would pass this test while
    // proving nothing about the finding.
    const row = page
      .locator("li")
      .filter({ hasText: /has no screen in any journey/ })
      .first();
    await row.getByRole("button", { name: /^Open Wireframes$/ }).click();
    await page.waitForTimeout(600);
    await expect(
      page.getByRole("button", { name: /Coverage/ }).first(),
    ).toBeVisible();
    await page.screenshot({ path: `${SHOTS}/20-jumped-to-wireframes.png` });
  });
});

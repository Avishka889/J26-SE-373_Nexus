import { expect, test, type Page } from "@playwright/test";

/**
 * The whole phase, in a browser, against a real model.
 *
 * Every other check in this directory runs on fixtures, which is right: they
 * assert things about four authored demo projects and they have to be
 * deterministic. This one asserts the opposite thing, and it is the one the
 * project is actually for. A thin sentence typed into the box, a design that
 * comes back from Groq, a question answered in the chat, a change requested, and
 * an approval, with nothing hand written anywhere in the path.
 *
 * It needs an orchestrator on VITE_API_URL with a database and a provider key, so
 * it is skipped unless LIVE_DESIGN is set. Run it with:
 *
 *   npm run dev -- --port 5173            (with .env.development, so live)
 *   LIVE_DESIGN=1 npx playwright test e2e/live-design.spec.ts \
 *     --config playwright.live.config.ts
 */

const SHOTS = process.env.SHOT_DIR ?? "/tmp/shots";
const REQUIREMENT = "Build a simple calculator app.";
const API = process.env.LIVE_API_URL ?? "http://localhost:8000";

/** The chevron labels, which are what a reader clicks. Stage ids are internal. */
const STAGE_LABELS: Record<string, RegExp> = {
  requirements: /Requirements Analysis/,
  "domain-model": /Domain Model/,
  "architecture-graph": /Architecture Graph/,
  "architecture-recommendation": /Architecture Recommendation/,
  "uml-diagrams": /UML Diagrams/,
  wireframes: /Wireframes/,
  "sprint-plan": /Sprint Planning/,
  "design-review": /Design Review/,
};

test.skip(!process.env.LIVE_DESIGN, "needs a live orchestrator; set LIVE_DESIGN=1");

test.use({
  viewport: { width: 1440, height: 900 },
  launchOptions: process.env.CHROME_PATH ? { executablePath: process.env.CHROME_PATH } : {},
});

// Six stages through a model, twice over, plus a gate.
test.setTimeout(15 * 60 * 1000);

async function login(page: Page) {
  await page.goto("/login");
  await page.getByLabel(/email/i).fill("alex@acme.dev");
  await page.getByLabel(/password/i).fill("demo");
  await page.getByRole("button", { name: /log in/i }).click();
  await expect(page).toHaveURL(/\/workspace/);
}

/**
 * Wait until the design has arrived and nothing is still being generated.
 *
 * Positive first, and that ordering is the whole point. Written the other way
 * round, as "wait for Generating to be hidden", it returned instantly: the page
 * still said "Loading the design", so the word it was waiting to disappear had
 * never appeared. A wait for an absence passes hardest when nothing has happened
 * yet.
 */
async function waitForDesign(page: Page, arrived: RegExp) {
  await expect(page.getByText(arrived).first()).toBeVisible({ timeout: 12 * 60 * 1000 });
  await expect(page.getByText(/Regenerating|Generating/i).first()).toBeHidden({
    timeout: 12 * 60 * 1000,
  });
}

/**
 * Open a stage by name, whatever the conversation panel happens to be doing.
 *
 * The full chevron row only exists with the conversation hidden, and the panel's
 * state persists across steps: hiding it twice fails, because the second time
 * there is no "hide" button to press. Three separate failures in this file were
 * that same assumption, so nothing assumes any more.
 */
async function openStage(page: Page, name: RegExp) {
  const hide = page.getByRole("button", { name: /hide the conversation/i });
  const stage = page.getByRole("button", { name });

  // Wait for either before deciding, which is what makes this safe straight after
  // a reload. Asking "is the hide button visible" on a page that has not finished
  // rendering answers no, and the condensed row it then searches has only the
  // active stage in it, so the click waited fifteen minutes for a chevron that was
  // never going to appear.
  await expect(hide.or(stage).first()).toBeVisible({ timeout: 2 * 60 * 1000 });

  if (await hide.isVisible().catch(() => false)) {
    await hide.click();
    await page.waitForTimeout(300);
  }
  await expect(stage.first()).toBeVisible({ timeout: 60_000 });
  await stage.first().click();
  await page.waitForTimeout(400);
}

/**
 * Press "Try again" on any stage that failed, which is what a reader does.
 *
 * Not a way of hiding a flake, and it reports every retry it needs so the rate
 * stays visible. On a five word brief the graph stage is genuinely marginal: the
 * model has almost nothing to work from and sometimes returns a graph the rules
 * refuse twice over. That is the case the retry button exists for, and a walk
 * through of the phase that could not survive one is testing luck rather than the
 * phase.
 *
 * Bounded, because a stage that fails twice is not flaky, it is broken, and the
 * walk should say so rather than grind.
 */
async function retryAnyFailedStage(
  page: Page,
  projectId: string,
  attemptsLeft = 2,
): Promise<number> {
  if (attemptsLeft === 0) return 0;

  // Which stage failed comes from the API, because the retry button only exists
  // on the stage the reader is looking at. Searching the current page for it found
  // nothing whenever the failure was somewhere else, which is most of the time.
  // The click itself is still the real button a reader presses.
  const snapshot = await (await page.request.get(`${API}/projects/${projectId}/design`)).json();
  const failed = Object.entries(snapshot.stages as Record<string, { status: string }>).find(
    ([, stage]) => stage.status === "failed",
  );
  if (!failed) return 0;

  const [stageId] = failed;
  const why: string = snapshot.stages[stageId].error ?? "";

  // A provider rate limit will not clear in the seconds a retry takes, so
  // pressing the button again just spends another call to be told the same thing.
  // Say so and stop: this is a quota problem, not a flaky stage, and reporting it
  // as a retry would hide which one it was.
  if (/rate limiting|out of quota/i.test(why)) {
    console.log(`  not retrying ${stageId}: ${why}`);
    return 0;
  }

  console.log(`  retrying ${stageId}: ${why.slice(0, 90)}`);
  await openStage(page, STAGE_LABELS[stageId]);
  await page.getByRole("button", { name: /^Try again$/ }).first().click();
  await expect(page.getByText(/Regenerating|Generating/i).first()).toBeHidden({
    timeout: 12 * 60 * 1000,
  });
  return 1 + (await retryAnyFailedStage(page, projectId, attemptsLeft - 1));
}

test("a sentence becomes an approved design, against a real model", async ({ page }) => {
  await login(page);

  // 1. A thin one line requirement, typed into the composer. The product is
  //    prompt first: there is no name field and no separate button that runs the
  //    pipeline, because the text arriving is the whole start signal.
  await page.goto("/projects/new");
  const composer = page.getByPlaceholder(/Describe a product/i);
  await composer.fill(REQUIREMENT);
  await composer.press("Enter");

  await expect(page).toHaveURL(/\/projects\/[^/]+\/requirements/, { timeout: 60_000 });
  const projectUrl = page.url();
  await page.screenshot({ path: `${SHOTS}/live-01-started.png`, fullPage: false });

  // 2. The real model answers, and answers honestly: assumptions and questions
  //    rather than a page of confident detail from five words.
  //
  //    Waited for by the last stage's own summary appearing in the transcript,
  //    because every stage posts one when it finishes. Waiting on something from
  //    the requirements card instead only worked by luck: when the run completes
  //    the phase has advanced to Wireframes, so nothing from the first stage is
  //    on the page at all.
  await expect(page.getByText(/Regenerating|Generating/i).first()).toBeHidden({
    timeout: 12 * 60 * 1000,
  });

  //    A stage that failed is retried the way a reader retries it, and the count
  //    is printed rather than swallowed: on a brief this thin the graph stage is
  //    marginal, and how often it needs a second go is a result.
  const retries = await retryAnyFailedStage(page, projectUrl.split('/projects/')[1].split('/')[0]);
  console.log(`  stage retries needed: ${retries}`);

  await waitForDesign(page, /Sprint Planning/i);
  await page.screenshot({ path: `${SHOTS}/live-02-generated.png` });

  //    Assumptions and questions live on the requirements stage, so go there
  //    rather than asserting against wherever the phase happened to land. The
  //    full chevron row needs the conversation hidden.
  await openStage(page, /Requirements Analysis/);
  await expect(page.getByText(/What was read from your input/i)).toBeVisible();
  await expect(page.getByText(/Assumed/i).first()).toBeVisible();
  await expect(page.getByText(/answer before approving/i)).toBeVisible();
  await page.screenshot({ path: `${SHOTS}/live-02b-requirements.png` });

  // 3. Answer one of them in the conversation, which is where a question is asked
  //    and where answering it clears it everywhere.
  //
  //    Targeted by its own placeholder rather than "the last textbox on the page".
  //    That is how this was first written, and it typed the answer into the
  //    requirements search filter: the answer never left the browser, three
  //    questions stayed open, and the test carried on as though it had worked.
  //    The panel was hidden above to reach the chevron row, so it is opened only
  //    if it is not already showing. Clicking the Conversation button
  //    unconditionally closed a panel that opens by default, and then the answer
  //    box was missing for the obvious reason.
  const answerBoxes = page.getByPlaceholder(/Answer in a sentence/i);
  if (!(await answerBoxes.first().isVisible())) {
    await page.getByRole("button", { name: /conversation/i }).first().click();
  }
  await expect(answerBoxes.first()).toBeVisible();
  const openBefore = await answerBoxes.count();
  expect(openBefore).toBeGreaterThan(0);

  await answerBoxes.first().fill("One person, on the web, and nothing is kept between sessions.");
  await answerBoxes.first().press("Enter");

  // Proof it landed, rather than a pause and a hope: strictly fewer questions
  // waiting for an answer than before.
  //
  // Fewer, not one fewer. The panel renders twice, once for the wide layout and
  // once for the drawer, so every question has two boxes and answering one
  // removes two. Asserting `openBefore - 1` encoded that layout detail and failed
  // on a run where the answer had actually landed.
  await expect
    .poll(() => answerBoxes.count(), { timeout: 30_000 })
    .toBeLessThan(openBefore);

  // And the answer itself is in the transcript, which is the positive half: the
  // count could fall for other reasons, the words could not.
  await expect(page.getByText(/nothing is kept between sessions/i).first()).toBeVisible();
  await page.screenshot({ path: `${SHOTS}/live-03-answered.png` });

  // 4. The gate. Everything generated, waiting on a person.
  await page.goto(projectUrl);
  await page.waitForLoadState("networkidle");
  await openStage(page, /Design Review/);
  await expect(page.getByRole("button", { name: "Decision", exact: true })).toBeVisible();
  await page.screenshot({ path: `${SHOTS}/live-04-gate.png` });

  // 5. One revision. The note is part of the input the regeneration reads, not a
  //    comment left beside it.
  await page.getByRole("button", { name: /request changes/i }).click();

  //    The composer's own controls, not "the last textbox" and not any button
  //    whose name contains send. Guessing those was how the note got typed into
  //    a search filter earlier in this file's history, and how it later went
  //    nowhere while the walk carried on as though a change had been requested.
  await expect(page.getByText(/What needs to change before this design is right/i)).toBeVisible();
  const note = page.getByPlaceholder(/Split the review queue/i);
  await note.fill("Add a memory function that stores the last result.");
  await page.getByRole("button", { name: "Send the note", exact: true }).click();

  //    The note is recorded as a decision and opens a new requirements version,
  //    which is the proof it was taken rather than typed.
  await expect(page.getByText(/Changes requested/i).first()).toBeVisible({ timeout: 60_000 });
  await page.screenshot({ path: `${SHOTS}/live-05-changes.png` });

  //    The regeneration is finished when the phase is showing version 2. That is
  //    the exact claim: a change note is part of the input and opens a new
  //    version, rather than a comment left beside the old one. Waiting for the
  //    note's own words instead was weaker than it looked, because the note is
  //    displayed in the decision panel and would have matched whether anything
  //    regenerated or not.
  //    "version 2" on the Requirements card, not the decision bar's own
  //    "Requirements version 2": the bar disappears once a decision exists, so
  //    that string is gone by the time this waits for it.
  await waitForDesign(page, /^version 2$/);
  await page.screenshot({ path: `${SHOTS}/live-06-regenerated.png` });

  // 6. Record which shape was chosen. The gate refuses to approve without it,
  //    which is the point: the decision has to say what was decided. Skipping
  //    this left Approve permanently disabled, and the walk sat waiting for a
  //    button that was never going to become clickable.
  await openStage(page, /Architecture Recommendation/);
  await page.getByRole("button", { name: /^Select / }).first().click();
  await expect(page.getByText(/^Selected$/).first()).toBeVisible({ timeout: 30_000 });
  await page.screenshot({ path: `${SHOTS}/live-06b-architecture.png` });

  // 7. Approve, and the phase says so.
  await openStage(page, /Design Review/);
  await page.getByRole("button", { name: /approve design/i }).click();
  await page.waitForTimeout(3_000);
  await expect(page.getByText(/Design approved/i).first()).toBeVisible({ timeout: 60_000 });
  await page.screenshot({ path: `${SHOTS}/live-07-approved.png` });
});

import { describe, expect, it } from "vitest";
import { buildTestSnapshot } from "../fixtures/buildTestSnapshot";
import {
  actorKindOf,
  approvalNote,
  atLine,
  buildView,
  counted,
  fileName,
  fixShipsWithLine,
  mutationTile,
  reverifiedToast,
  shortPath,
  unprovenIn,
} from "./view";
import type { Reverification, TestReport, TestSnapshot } from "../api/types";

/**
 * The one derivation, tested where it is now testable.
 *
 * It used to read hand written demo data through nine parameters of client
 * held state, and the only thing under test was a two line path helper. It is
 * now a pure function of one snapshot, so the counts the page shows can be
 * checked against the artefacts they came from.
 *
 * The rules being held are the phase's, not the demo's: a refusal is a result,
 * a decision belongs to a version, and nothing is claimed that was not
 * measured.
 */

const view = (posture: Parameters<typeof buildTestSnapshot>[1] = "awaiting") =>
  buildView({ data: buildTestSnapshot("p1", posture, 1), reviewer: "you" });

describe("paths", () => {
  it("returns the last path segment", () => {
    expect(fileName("backend/src/PaymentControllerTest.java")).toBe("PaymentControllerTest.java");
  });

  it("handles bare filenames", () => {
    expect(fileName("README.md")).toBe("README.md");
  });

  it("shortens to the last two segments", () => {
    expect(shortPath("src/main/java/com/example/Accounts.java")).toBe("example/Accounts.java");
  });

  // A live failure carries no line, and every link read "file.test.ts:0".
  it("names a line only when one is known", () => {
    expect(atLine("books.test.ts", 12)).toBe("books.test.ts:12");
    expect(atLine("books.test.ts", 0)).toBe("books.test.ts");
    expect(atLine("books.test.ts", null)).toBe("books.test.ts");
  });
});

describe("counted nouns", () => {
  it("says 1 finding, not 1 findings", () => {
    expect(counted(1, "finding", "findings")).toBe("1 finding");
    expect(counted(0, "finding", "findings")).toBe("0 findings");
    expect(counted(3, "fix", "fixes")).toBe("3 fixes");
  });
});

describe("nothing is claimed that was not measured", () => {
  it("a phase that never ran shows no counts at all", () => {
    const empty = view("not-started");

    expect(empty.build).toBe(0);
    expect(empty.totals.run).toBe(0);
    expect(empty.findings).toEqual([]);
    expect(empty.failures).toEqual([]);
    expect(empty.transcript).toEqual([]);
  });

  it("a phase that never ran is not waiting on a decision", () => {
    expect(view("not-started").decisionPending).toBe(false);
  });

  it("a step that has not run reads pending rather than done", () => {
    const steps = view("not-started").steps;

    expect(steps["test-run"].state).toBe("pending");
    expect(steps["security-scan"].state).toBe("pending");
  });

  it("mutation that did not run says so rather than scoring zero", () => {
    const snapshot = buildTestSnapshot("p1", "awaiting", 1);
    const without = {
      ...snapshot,
      tests: { ...snapshot.tests!, mutation: null, mutationSkippedReason: "the suite was red" },
    } as TestSnapshot;

    const derived = buildView({ data: without, reviewer: "you" });

    expect(derived.quality.trendNote).toBe("the suite was red");
  });
});

describe("the counts come from the artefacts", () => {
  it("totals come from the test report", () => {
    const snapshot = buildTestSnapshot("p1", "awaiting", 1);
    const derived = buildView({ data: snapshot, reviewer: "you" });

    expect(derived.totals.run).toBe(Number(snapshot.tests!.total));
    expect(derived.totals.failed).toBe(Number(snapshot.tests!.failed));
    expect(derived.totals.passRate).toBeCloseTo(
      (Number(snapshot.tests!.passed) / Number(snapshot.tests!.total)) * 100,
      5,
    );
  });

  it("a suite's requirements are every one its cases trace to", () => {
    const [module] = view().modules;

    expect(module.requirements).toContain("R-4");
    expect(new Set(module.requirements).size).toBe(module.requirements.length);
  });

  it("the security list is the findings, dismissals included", () => {
    const derived = view();

    expect(derived.findings).toHaveLength(3);
    expect(derived.findingCounts.dismissed).toBe(1);
    // One of the two undismissed findings has a fix proposed, which is not
    // resolved either.
    expect(derived.findingCounts.open).toBe(1);
    expect(derived.findingCounts.proposed).toBe(1);
    expect(derived.findingCounts.toResolve).toBe(2);
  });

  it("a dismissed finding is not something left to resolve", () => {
    expect(view().findingCounts.toResolve).toBe(2);
  });
});

describe("a refusal is a result", () => {
  it("a repair the guard rejected is shown, not hidden", () => {
    const refused = view().failures.find((one) => one.state === "blocked");

    expect(refused).toBeDefined();
    expect(refused?.repair?.verdictLine).toContain("Refused");
  });

  it("the refused repair carries the diff a reader has to judge", () => {
    const refused = view().failures.find((one) => one.state === "blocked");

    expect(refused?.repair?.proposed).toContain("toBeDefined");
  });

  it("its failing guard check says which one failed and why", () => {
    const refused = view().failures.find((one) => one.state === "blocked");

    expect(refused?.repair?.guard.planted.pass).toBe(false);
    expect(refused?.repair?.guard.planted.detail).toContain("0 of 3");
  });

  it("a regression is flagged and never healed", () => {
    const regression = view().failures.find((one) => one.triage === "regression");

    expect(regression?.state).toBe("escalated");
    expect(regression?.repair).toBeUndefined();
    expect(regression?.reason).toContain("did not change");
  });

  it("a regression written after the change does not say its requirements stood still", () => {
    // Written from the changed requirements, it traces to what changed, so
    // "did not change" would be false about it.
    const base = buildTestSnapshot("p1", "awaiting", 1);
    const heal = base.heal && {
      ...base.heal,
      attempts: base.heal.attempts.map((one) =>
        one.classification === "regression"
          ? {
              ...one,
              classifiedBy: "written-after-change" as const,
              evidence: { ...one.evidence, changedArtefacts: ["R-9"] },
            }
          : one,
      ),
    };

    const regression = buildView({ data: { ...base, heal }, reviewer: "you" }).failures.find(
      (one) => one.triage === "regression",
    );

    expect(regression?.reason).not.toContain("did not change");
    expect(regression?.reason).toContain("written after the requirements changed");
  });

  it("the inbox counts each kind apart", () => {
    const { inbox } = view();

    expect(inbox.healed).toBe(1);
    expect(inbox.regressions).toBe(1);
    expect(inbox.brittle).toBe(1);
  });
});

describe("a repair to an API test", () => {
  // Every run writes the API tests again from the contract, so the server
  // refuses to keep a repair to one, and the page says so instead of offering it.
  it("is marked as one every run writes again", () => {
    const data = structuredClone(buildTestSnapshot("p1", "awaiting", 1));
    const [first] = (data.tests?.suites ?? [])
      .flatMap((suite) => suite.cases)
      .filter((one) => one.outcome === "failed");
    first.kind = "api";

    const failures = buildView({ data, reviewer: "you" }).failures;

    expect(failures.find((one) => one.id === first.id)?.rewrittenEachRun).toBe(true);
    expect(failures.filter((one) => one.id !== first.id).some((one) => one.rewrittenEachRun)).toBe(
      false,
    );
  });
});

describe("a decision belongs to the version it was made about", () => {
  it("an approval of this version stands", () => {
    const approved = view("approved");

    expect(approved.decision?.kind).toBe("approved");
    expect(approved.superseded).toBeNull();
    expect(approved.progress).toBe(100);
  });

  it("an approval is superseded once the code moves on", () => {
    const snapshot = buildTestSnapshot("p1", "approved", 1);
    const moved = { ...snapshot, codeVersion: 2, codeMovedOn: true } as TestSnapshot;

    const derived = buildView({ data: moved, reviewer: "you" });

    expect(derived.decision).toBeNull();
    expect(derived.superseded?.kind).toBe("approved");
    expect(derived.decisionPending).toBe(true);
  });

  it("the report step says it is waiting again rather than done", () => {
    const snapshot = buildTestSnapshot("p1", "approved", 1);
    const moved = { ...snapshot, codeVersion: 2, codeMovedOn: true } as TestSnapshot;

    expect(buildView({ data: moved, reviewer: "you" }).steps["test-review"].hint).toBe(
      "waiting on you again",
    );
  });
});

describe("a stage in flight", () => {
  it("reads as running rather than as finished", () => {
    const running = view("running");

    expect(running.streaming).toBe(true);
    expect(running.steps["test-run"].state).toBe("running");
  });

  it("does not offer a decision while work is outstanding", () => {
    expect(view("running").decisionPending).toBe(false);
  });
});

describe("a stage that does not apply to this target", () => {
  /**
   * Test generation writes TypeScript from the API contract, so a Java
   * repository gives it nothing to write. Skipping is not failing and it is
   * not completing either, and the step has to say which it was.
   */
  it("reads as not run, with the reason the server gave", () => {
    const snapshot = buildTestSnapshot("p1", "approved", 1);
    snapshot.stages["security-scan"] = {
      ...snapshot.stages["security-scan"],
      status: "skipped",
      summary: "no scanner reads this stack",
    };

    const view = buildView({ data: snapshot, reviewer: "you" });

    expect(view.steps["security-scan"].state).toBe("pending");
    expect(view.steps["security-scan"].hint).toBe("no scanner reads this stack");
  });

  it("is not reported as done", () => {
    const snapshot = buildTestSnapshot("p1", "approved", 1);
    snapshot.stages["test-quality"] = {
      ...snapshot.stages["test-quality"],
      status: "skipped",
      summary: "mutation needs a green suite",
    };

    const view = buildView({ data: snapshot, reviewer: "you" });

    expect(view.steps["test-quality"].state).not.toBe("done");
  });

  it("still tells a stage that has not started from one that never will", () => {
    const snapshot = buildTestSnapshot("p1", "approved", 1);
    snapshot.stages["test-quality"] = { ...snapshot.stages["test-quality"], status: "pending" };

    const view = buildView({ data: snapshot, reviewer: "you" });

    expect(view.steps["test-quality"].state).toBe("pending");
    expect(view.steps["test-quality"].hint).toBe("waits for the run");
  });
});

describe("what holds the test review", () => {
  /**
   * Book Tracker's review was approved over a red test, and Deployment's staging
   * build then ran the same test and refused the candidate. The server now
   * refuses that approval; the page names the tests it is refused over.
   */
  const at = (target: string) =>
    ({ ...buildTestSnapshot("p1", "awaiting", 1), target }) as TestSnapshot;

  it("lists a generated app's failing tests by name", () => {
    const snapshot = at("generated");
    const failed = snapshot.tests!.suites.flatMap((suite) =>
      suite.cases.filter((one) => one.outcome === "failed").map((one) => one.name),
    );

    expect(failed.length).toBeGreaterThan(0);
    expect(buildView({ data: snapshot, reviewer: "you" }).failingTests).toEqual(failed);
  });

  it("lists none for a sample, whose failures are seeded on purpose", () => {
    expect(buildView({ data: at("sample:java"), reviewer: "you" }).failingTests).toEqual([]);
  });
});

describe("the mutation tile", () => {
  it("counts the mutants the report lists by id", () => {
    // The contract's shape: killed and survived are the mutants' ids. A live
    // page read them with `Number` and showed "NaN killed · NaN survived".
    const snapshot = buildTestSnapshot("p1", "awaiting", 1);
    const live = {
      ...snapshot,
      tests: {
        ...snapshot.tests!,
        mutation: { ...snapshot.tests!.mutation!, killed: ["m1", "m2", "m3"], survived: ["m4"] },
      },
    } as TestSnapshot;

    const quality = buildView({ data: live, reviewer: "you" }).quality;

    expect(quality.mutation.killed).toBe(3);
    expect(quality.mutation.survived).toBe(1);
  });
});

/**
 * The review's failing tests are what the run measured.
 *
 * The page read the newest target choice, which may change while a review
 * waits: choosing a sample emptied the list and enabled Approve over the
 * generated app's failing run.
 */
describe("the failing tests the review shows", () => {
  function measured(target: string, report: string): TestSnapshot {
    const snapshot = buildTestSnapshot("p1", "awaiting", 1);
    return {
      ...snapshot,
      target,
      tests: snapshot.tests && {
        ...snapshot.tests,
        target: report,
        suites: [
          {
            path: "apps/web/src/__tests__/generated.test.ts",
            framework: "vitest",
            cases: [
              {
                id: "c1",
                name: "a person sees the result",
                outcome: "failed",
                message: "expected 5, received 6",
                traces: { storyId: "US-1", criterionId: "AC-1-1" },
              },
            ],
          },
        ],
      },
    } as TestSnapshot;
  }

  it("stay when the target is switched to a sample after the run", () => {
    const view = buildView({
      data: measured("sample:java", "the generated app at code version 6"),
      reviewer: "you",
    });

    expect(view.failingTests).toEqual(["a person sees the result"]);
  });

  it("are none for a run that measured a sample, whose failures are seeded", () => {
    const view = buildView({ data: measured("generated", "the java sample"), reviewer: "you" });

    expect(view.failingTests).toEqual([]);
  });
});

/**
 * A finding carries the fix proposed for it.
 *
 * The page never joined the two: proposals sat in the snapshot's remediation,
 * every finding opened to "Nothing to apply yet", and Apply fix, Dismiss and
 * the re-verification behind them could not be reached on a live page.
 */
describe("a security finding", () => {
  it("carries the fix proposed for it", () => {
    const data = buildTestSnapshot("p1", "awaiting", 1);
    const proposal = data.remediation?.proposals.find((one) => one.findingId === "CWE-89:orders:36");
    if (!proposal) throw new Error("the demo proposes a fix for CWE-89:orders:36");

    const finding = buildView({ data, reviewer: "you" }).findings.find((one) => one.id === "CWE-89:orders:36");

    expect(finding?.proposal).toEqual({
      id: proposal.id,
      summary: proposal.summary,
      hunks: proposal.patch,
      state: proposal.state,
      risk: proposal.risk.statement,
      appliedCodeVersion: null,
    });
    expect(finding?.status).toBe("fix-proposed");
  });

  it("stays to resolve once its fix is applied, until a re-verification passes", () => {
    const data = buildTestSnapshot("p1", "awaiting", 1);
    const settle = (state: "applied" | "verified") => ({
      ...data,
      remediation: data.remediation && {
        ...data.remediation,
        proposals: data.remediation.proposals.map((one) =>
          one.findingId === "CWE-89:orders:36" ? { ...one, state, appliedCodeVersion: 4 } : one,
        ),
      },
    });
    const before = buildView({ data, reviewer: "you" }).findingCounts.toResolve;

    const applied = buildView({ data: settle("applied"), reviewer: "you" });
    const verified = buildView({ data: settle("verified"), reviewer: "you" });

    expect(applied.findings.find((one) => one.id === "CWE-89:orders:36")?.status).toBe("fix-applied");
    expect(applied.findingCounts.toResolve).toBe(before);
    expect(verified.findings.find((one) => one.id === "CWE-89:orders:36")?.status).toBe("verified");
    expect(verified.findingCounts.toResolve).toBe(before - 1);
  });
});

/**
 * The approval's note counts every finding still open, as the gate's own
 * audit entry does. A finding whose fix is proposed or applied but not yet
 * re-verified is still an open weakness, and counting only the untouched ones
 * understated what an approval left behind.
 */
describe("the note an approval carries", () => {
  it("counts a finding with a fix not yet re-verified as open", () => {
    const derived = buildView({ data: buildTestSnapshot("p1", "awaiting", 1), reviewer: "you" });

    expect(derived.findingCounts.proposed).toBeGreaterThan(0);
    expect(approvalNote(derived)).toBe(`Approved with ${derived.findingCounts.toResolve} findings open.`);
  });
});

/**
 * The decision bar showed when no review was waiting (after a failed run, a
 * retired run, or code that moved on), and both its buttons were refused.
 */
describe("whether testing offers a decision, when the server's run is known", () => {
  const withRun = (state: string, codeMovedOn = false) => {
    const snapshot = buildTestSnapshot("p1", "awaiting", 1);
    return buildView({
      data: { ...snapshot, codeMovedOn, run: { id: "r1", state, version: snapshot.testVersion, startedAt: "2026-10-03T09:00:00Z", finishedAt: null, error: null, stoppedAt: null } } as TestSnapshot,
      reviewer: "you",
    }).decisionPending;
  };

  it("offers it while the run waits at its review", () => {
    expect(withRun("awaiting_gate")).toBe(true);
  });

  it("does not after the run failed or was retired, or once the code moved on", () => {
    expect(withRun("failed")).toBe(false);
    expect(withRun("superseded")).toBe(false);
    expect(withRun("awaiting_gate", true)).toBe(false);
  });
});

/**
 * Skipped tests counted as run: "24 of 27 run, pass rate 88.9%" with nothing
 * failing, and Generation counted the declared tests twice, in the suite and
 * as declared.
 */
describe("what ran", () => {
  it("is what passed or failed, and the pass rate is of those", () => {
    const snapshot = buildTestSnapshot("p1", "awaiting", 1);
    const data = {
      ...snapshot,
      tests: { ...snapshot.tests!, total: 27, passed: 24, failed: 0, skipped: 3 },
    } as TestSnapshot;

    const { totals } = buildView({ data, reviewer: "you" });

    expect(totals).toMatchObject({ run: 24, passed: 24, skipped: 3, passRate: 100 });
  });
});

/**
 * Mutation showed a measured "0%" for a version it never ran on, and the
 * survivors that existed were hidden behind "the full mutation report", which
 * nothing produces.
 */
describe("mutation testing", () => {
  const qualityWith = (mutation: unknown, mutationSkippedReason = "") => {
    const snapshot = buildTestSnapshot("p1", "awaiting", 1);
    return buildView({
      data: {
        ...snapshot,
        tests: { ...snapshot.tests!, mutation, mutationSkippedReason },
      } as unknown as TestSnapshot,
      reviewer: "you",
    }).quality;
  };

  it("says it did not run, and why, rather than scoring it", () => {
    const quality = qualityWith(null, "Stryker found no tests to mutate against.");

    expect(quality.mutationRan).toBe(false);
    expect(quality.mutationSkippedReason).toBe("Stryker found no tests to mutate against.");
  });

  it("lists each survivor from its address, in words", () => {
    const quality = qualityWith({
      tool: "Stryker",
      total: 3,
      killed: ["apps/web/src/format.ts:3:1:StringLiteral"],
      survived: [
        "apps/web/src/format.ts:12:5:ArithmeticOperator",
        "apps/api/src/books.ts:40:9:ConditionalExpression",
      ],
      score: 33.3,
    });

    expect(quality.mutationRan).toBe(true);
    expect(quality.survivors).toEqual([
      { location: "format.ts:12", change: "an arithmetic operator was swapped", note: "No test noticed." },
      { location: "books.ts:40", change: "a condition was forced true or false", note: "No test noticed." },
    ]);
  });
});

/**
 * A review waiting while the code moved on is of code that is no longer
 * current. It is not offered for deciding, and running the tests again, which
 * the page offers, closes it.
 */
describe("a review the code has moved past", () => {
  function waiting(codeMovedOn: boolean): TestSnapshot {
    const data = structuredClone(buildTestSnapshot("p1", "awaiting", 1));
    return {
      ...data,
      codeMovedOn,
      codeVersion: codeMovedOn ? data.testedCodeVersion + 1 : data.testedCodeVersion,
      run: {
        id: "run-1",
        state: "awaiting_gate",
        version: data.testVersion,
        model: "deepseek:deepseek-flash",
        thinking: "disabled",
        startedAt: "2026-10-04T09:00:00+00:00",
        finishedAt: null,
        stoppedAt: null,
        error: null,
      },
    };
  }

  it("is not offered for deciding, and says it is one", () => {
    const moved = buildView({ data: waiting(true), reviewer: "you" });

    expect(moved.decisionPending).toBe(false);
    expect(moved.reviewMovedPast).toBe(true);
  });

  it("is decided as ever while the code is the code it tested", () => {
    const current = buildView({ data: waiting(false), reviewer: "you" });

    expect(current.decisionPending).toBe(true);
    expect(current.reviewMovedPast).toBe(false);
  });
});

/**
 * A failure nothing has classified is not a regression.
 *
 * With no earlier tested version, healing compares nothing, and every failure
 * was filed under "Real regressions" with "needing a code change" in the bar,
 * sending a reader to change code that may be right. One wrong generated test
 * then held the review for good; a person can now set it aside, with a reason.
 */
describe("a failure nothing has classified", () => {
  function firstRun(
    decisions: TestSnapshot["healDecisions"] = [],
    outcome: "failed" | "skipped" = "failed",
  ): TestSnapshot {
    const snapshot = buildTestSnapshot("p1", "awaiting", 1);
    return {
      ...snapshot,
      target: "generated",
      heal: null,
      healDecisions: decisions,
      tests: snapshot.tests && {
        ...snapshot.tests,
        target: "the generated app at code version 1",
        suites: [
          {
            path: "apps/api/src/__tests__/us-1.criteria.test.ts",
            framework: "vitest",
            cases: [
              {
                id: "c1",
                name: "US-1 a record is kept",
                outcome,
                message: outcome === "failed" ? "expected 5, received 6" : "",
                traces: { storyId: "US-1", criterionId: "AC-1-1" },
              },
            ],
          },
        ],
      },
    } as TestSnapshot;
  }

  it("is not classified, and says why, on a first run", () => {
    const view = buildView({ data: firstRun(), reviewer: "you" });
    const [failure] = view.failures;

    expect(failure.triage).toBe("unclassified");
    expect(failure.reason).toMatch(/No earlier tested version to compare with/);
    expect(view.inbox.regressions).toBe(0);
    expect(view.inbox.unclassified).toBe(1);
  });

  it("set aside by quarantine, holds the review up no longer", () => {
    const view = buildView({
      data: firstRun([
        { testId: "c1", decision: "quarantined", by: "Ana", at: "2026-10-05T10:00:00Z", note: "wrong" },
      ]),
      reviewer: "you",
    });
    const [failure] = view.failures;

    expect(failure.state).toBe("quarantined");
    expect(failure.setAside).toMatchObject({ decision: "quarantined", by: "Ana", note: "wrong" });
    expect(view.failingTests).toEqual([]);
    expect(view.inbox.needsAttention).toBe(0);
  });

  it("sent back to be written again, still holds it until the next run", () => {
    const view = buildView({
      data: firstRun([
        { testId: "c1", decision: "rewrite", by: "Ana", at: "2026-10-05T10:00:00Z", note: "wrong" },
      ]),
      reviewer: "you",
    });

    expect(view.failures[0].setAside?.decision).toBe("rewrite");
    expect(view.failingTests).toEqual(["US-1 a record is kept"]);
  });

  // Every later run skips it, and the quarantine stays in force until somebody
  // restores it, so the page has to keep showing it to make that possible.
  it("stays listed once later runs skip it, so it can be restored", () => {
    const view = buildView({
      data: firstRun(
        [{ testId: "c1", decision: "quarantined", by: "Ana", at: "2026-10-05T10:00:00Z", note: "wrong" }],
        "skipped",
      ),
      reviewer: "you",
    });

    expect(view.failures.map((one) => [one.id, one.state])).toEqual([["c1", "quarantined"]]);
    expect(view.failingTests).toEqual([]);
  });

  it("lists no skipped test nobody quarantined", () => {
    const view = buildView({ data: firstRun([], "skipped"), reviewer: "you" });

    expect(view.failures).toEqual([]);
  });
});

/**
 * Only a failure held an approval up. A workspace that would not install
 * returned a report with no tests in it, and the page said "every proof
 * passed" over it.
 */
describe("what a run did not prove", () => {
  type Case = { id: string; outcome: string };
  const report = (cases: Case[], steps: { name: string; outcome: string }[] = [], path = "apps/api/src/__tests__/a.test.ts") =>
    ({
      suites: cases.length ? [{ path, framework: "vitest", cases }] : [],
      steps: steps.map((step) => ({ ...step, command: step.name, durationSeconds: 0, logTail: "" })),
    }) as unknown as TestReport;

  it("names a run in which no test ran, and the step that stopped it", () => {
    expect(unprovenIn(report([], [{ name: "install", outcome: "failed" }]), new Set())).toEqual([
      "no test ran: install failed",
    ]);
  });

  it("names an app that produced no report", () => {
    const run = report(
      [{ id: "c1", outcome: "passed" }],
      [
        { name: "tests (apps/api)", outcome: "failed" },
        { name: "tests (apps/web)", outcome: "passed" },
      ],
      "apps/web/src/__tests__/a.test.ts",
    );

    expect(unprovenIn(run, new Set())).toEqual(["apps/api produced no test report"]);
  });

  it("counts the criteria still declared, and not a quarantined test", () => {
    const run = report([
      { id: "c1", outcome: "passed" },
      { id: "c2", outcome: "skipped" },
      { id: "c3", outcome: "skipped" },
    ]);

    expect(unprovenIn(run, new Set(["c3"]))).toEqual(["1 acceptance criterion declared and not written"]);
  });

  it("is nothing for a run that measured everything", () => {
    expect(unprovenIn(report([{ id: "c1", outcome: "passed" }]), new Set())).toEqual([]);
  });
});

// C3-10: the review could not tell this version's new tests from the regression
// suite carried forward, and a test whose criterion had left the plan passed as
// if it still tested the build. Each case now says both, and the page counts it.
describe("each test says where it stands", () => {
  const OBSOLETE = "AC-1-9 is no longer one of US-1's acceptance criteria";

  function standing(stamps: Array<[number, string]>) {
    const snapshot = buildTestSnapshot("p1", "awaiting", 1);
    const tests = snapshot.tests!;
    const [suite] = tests.suites;
    const cases = stamps.map(([sinceVersion, obsolete], index) => ({
      ...suite.cases[0],
      id: `case-${index}`,
      name: `case ${index}`,
      sinceVersion,
      obsolete,
    }));
    const data = { ...snapshot, tests: { ...tests, version: 3, suites: [{ ...suite, cases }] } };
    return { view: buildView({ data, reviewer: "you" }), module: fileName(suite.path) };
  }

  it("counts a module's new tests apart from the ones it carried", () => {
    const { view } = standing([
      [3, ""],
      [1, ""],
      [2, OBSOLETE],
    ]);

    expect(view.modules[0].fresh).toBe(1);
    expect(view.modules[0].carried).toBe(2);
  });

  it("lists the tests that no longer test the build, and why", () => {
    const { view, module } = standing([
      [3, ""],
      [2, OBSOLETE],
    ]);

    expect(view.obsolete).toEqual([{ id: "case-1", name: "case 1", module, reason: OBSOLETE }]);
  });

  it("a report stored before this was recorded claims neither", () => {
    const { view } = standing([[0, ""]]);

    expect(view.modules[0].fresh).toBe(0);
    expect(view.modules[0].carried).toBe(0);
    expect(view.obsolete).toEqual([]);
  });
});

/**
 * A fix patches the newest code version, so over newer code than may ship it
 * reaches production only with that code (review item C4-13). Nothing said so.
 */
describe("where a fix ships", () => {
  it("names the sprint it ships with, when the newer code is a later sprint", () => {
    expect(
      fixShipsWithLine({ codeVersion: 3, sprint: 2, releasableCodeVersion: 2, releasableSprint: 1 }),
    ).toBe(
      "A fix applied now goes into code version 3, sprint 2's build, and reaches production with sprint 2, once its tests are approved. Code version 2 (sprint 1), the newest with approved tests, does not get it on its own.",
    );
  });

  it("names the newer code itself, when it is the same sprint", () => {
    expect(
      fixShipsWithLine({ codeVersion: 4, sprint: 1, releasableCodeVersion: 2, releasableSprint: 1 }),
    ).toBe(
      "A fix applied now goes into code version 4, the newest code, and reaches production with the rest of it, once its tests are approved. Code version 2, the newest with approved tests, does not get it on its own.",
    );
  });

  it("says nothing when a fix ships on its own, and the view carries what the snapshot says", () => {
    expect(fixShipsWithLine(null)).toBeNull();
    const data = {
      ...buildTestSnapshot("p1", "awaiting", 1),
      fixShipsWith: { codeVersion: 3, sprint: 2, releasableCodeVersion: 2, releasableSprint: 1 },
    };
    expect(buildView({ data, reviewer: "you" }).fixShipsWith).toContain("sprint 2's build");
    expect(view().fixShipsWith).toBeNull();
  });
});

describe("a finding's decisions", () => {
  // The release gate reads the reason a risk was accepted (G8); the page showed none.
  it("carries the reason its risk was accepted", () => {
    const base = buildTestSnapshot("p1", "awaiting", 1);
    const [first] = base.validation?.findings ?? [];
    if (!first) throw new Error("the fixture has a finding");
    const data = {
      ...base,
      findingDecisions: [
        {
          findingId: first.id,
          decision: "accepted" as const,
          by: "you",
          at: "2026-10-09T10:00:00+00:00",
          note: "Behind the admin login until sprint 2.",
        },
      ],
    };

    const finding = buildView({ data, reviewer: "you" }).findings.find((one) => one.id === first.id);

    expect(finding?.riskAccepted).toBe("Behind the admin login until sprint 2.");
  });
});

describe("a fix applied and not yet tested", () => {
  // A second fix applied before the first one's version was tested left the first
  // impossible to re-verify; the server refuses it, and the page says so first (C3-9).
  it("names itself and the version a run must measure first", () => {
    const base = buildTestSnapshot("p1", "awaiting", 1);
    const [first] = base.remediation?.proposals ?? [];
    if (!first) throw new Error("the fixture proposes a fix");
    const made = base.testedCodeVersion + 1;
    const data = {
      ...base,
      codeVersion: made,
      remediation: base.remediation && {
        ...base.remediation,
        proposals: [{ ...first, state: "applied" as const, appliedCodeVersion: made }],
      },
    };

    expect(buildView({ data, reviewer: "you" }).fixAwaitingItsRun).toBe(
      `The ${first.cwe} fix in ${first.patch[0]?.path} is applied as code version ${made}, which no testing run has measured yet: run the tests on code version ${made} first, then apply another fix.`,
    );
    // Once a run measures that version, the next fix can go on.
    expect(buildView({ data: { ...data, testedCodeVersion: made }, reviewer: "you" }).fixAwaitingItsRun).toBeNull();
    expect(view().fixAwaitingItsRun).toBeNull();
  });
});

describe("re-verifying a fix", () => {
  // Totals that held called a fix verified with its own finding still raised (C3-7).
  const numbers = { mutationScore: null, openFindings: 1, testsFailed: 0, testsPassed: 4 };
  const comparison = (overrides: Partial<Reverification> = {}): Reverification => ({
    before: { ...numbers, openFindings: 2 },
    after: numbers,
    beforeRunId: "r1",
    afterRunId: "r2",
    findingId: "CWE-89:accounts:6",
    stillRaisedAs: [],
    findingsClosed: 1,
    testsBroken: 0,
    worsened: false,
    findingClosed: true,
    verified: true,
    ...overrides,
  });
  const fixAfter = (verification: Reverification) => {
    const base = buildTestSnapshot("p1", "awaiting", 1);
    const [first] = base.remediation?.proposals ?? [];
    if (!first) throw new Error("the fixture proposes a fix");
    const data = {
      ...base,
      remediation: base.remediation && {
        ...base.remediation,
        proposals: [{ ...first, state: "applied" as const, appliedCodeVersion: 2, reverification: verification }],
      },
    };
    return buildView({ data, reviewer: "you" }).fixes[0];
  };

  it("passes the scan when the finding it was for is gone", () => {
    const fix = fixAfter(comparison());

    expect([fix?.scan.state, fix?.suite.state]).toEqual(["pass", "pass"]);
    expect(fix?.scan.detail).toBe("The finding it was for is gone");
    expect(fix?.verdict).toBe("Fixed and re-verified.");
    expect(reverifiedToast(comparison())).toEqual({
      type: "success",
      title: "Re-verified",
      message: "The finding it was for is gone, and no test broke.",
    });
  });

  it("fails the scan while that finding is still raised, though nothing broke", () => {
    const still = comparison({
      after: { ...numbers, openFindings: 2 },
      findingsClosed: 0,
      stillRaisedAs: ["CWE-89:accounts:7"],
      findingClosed: false,
      verified: false,
    });
    const fix = fixAfter(still);

    expect([fix?.scan.state, fix?.suite.state]).toEqual(["fail", "pass"]);
    expect(fix?.scan.detail).toBe("The finding is still raised after the fix");
    expect(fix?.verdict).toBe(
      "Not verified: the scan still raises the finding this fix was for, so it did not close it.",
    );
    expect(reverifiedToast(still)).toEqual({
      type: "error",
      title: "Not verified",
      message: "The scan still raises the finding this fix was for, so it did not close it.",
    });
  });

  it("names what broke when the numbers got worse", () => {
    const broke = comparison({ testsBroken: 2, worsened: true, verified: false });

    expect(fixAfter(broke)?.suite.state).toBe("fail");
    expect(fixAfter(broke)?.verdict).toBe("Not verified: 2 tests broke, so a rollback is offered.");
    expect(reverifiedToast(broke).message).toBe("2 tests broke, so a rollback is offered.");
  });

  it("asks again when the comparison never looked for the finding", () => {
    const totals = comparison({ findingId: "", findingClosed: false, verified: false });
    const fix = fixAfter(totals);

    expect(fix?.scan.state).toBe("pending");
    expect(fix?.verdict).toBe(
      "This comparison counted totals only and did not look for the finding itself: re-verify to check it.",
    );
    expect(fix?.pendingNote).toBe(
      "Re-verifying compares the same two runs again, and looks for the finding itself in the scan after the fix.",
    );
  });
});

describe("a mutation score", () => {
  // The page showed 0% wherever mutation never ran (review item C3-6).
  const withMutation = (mutation: TestReport["mutation"], reason = "") => {
    const base = buildTestSnapshot("p1", "awaiting", 1);
    const tests = base.tests && { ...base.tests, mutation, mutationSkippedReason: reason };
    return buildView({ data: { ...base, tests }, reviewer: "you" });
  };
  const measured: NonNullable<TestReport["mutation"]> = {
    tool: "stryker 9.0.1",
    scope: ["apps/api/src/routes/movies.ts"],
    killed: ["apps/api/src/routes/movies.ts:1:1:BooleanLiteral"],
    survived: ["apps/api/src/routes/movies.ts:2:1:BooleanLiteral"],
    inconclusive: [],
    durationSeconds: 12,
    notMeasured: [],
    total: 2,
    score: 50,
  };

  it("is not measured when mutation did not run, wherever it shows", () => {
    const view = withMutation(null, "the suite has failing tests");

    expect(mutationTile(view.quality)).toEqual({ value: "Not measured", note: "mutation did not run" });
    expect(view.steps["test-quality"].hint).toBe("mutation not measured");
  });

  it("counts the mutants rather than listing them", () => {
    const view = withMutation(measured);

    expect(mutationTile(view.quality)).toEqual({ value: "50%", note: "1 killed · 1 survived" });
    expect(view.steps["test-quality"].hint).toBe("mutation score 50%");
    expect(view.quality.trendNote).toBe("1 of 2 mutants killed");
  });

  it("says which app gave no score", () => {
    const reason = "the mutation run failed and left no report";
    const view = withMutation({ ...measured, notMeasured: [{ app: "apps/web", reason }] });

    expect(mutationTile(view.quality).note).toBe("1 killed · 1 survived · apps/web not measured");
    expect(view.quality.mutationNotMeasured).toEqual([{ app: "apps/web", reason }]);
  });
});

describe("the tools a scan ran", () => {
  // npm audit never ran on a generated app, and only the stage's notes said so (C3-5).
  it("says each tool's outcome, and why one did not run", () => {
    const base = buildTestSnapshot("p1", "awaiting", 1);
    const tools = [
      { tool: "semgrep", ran: true, version: "1.90.0", detail: "" },
      { tool: "npm audit", ran: false, version: "", detail: "npm reported ENOTFOUND: request failed" },
    ];
    const data = { ...base, validation: base.validation && { ...base.validation, tools } };

    expect(buildView({ data, reviewer: "you" }).scanTools).toEqual([
      "semgrep 1.90.0 ran",
      "npm audit did not run: npm reported ENOTFOUND: request failed",
    ]);
  });
});

/**
 * A first run has no earlier version to compare with, so nothing classifies
 * its failures, and the page put that sentence where the failure's own message
 * goes. All three failures of a live run were real defects ("expected 404 to
 * be less than 400"), and the reviewer was asked to decide them without it.
 */
describe("what a first run's failure says", () => {
  const MESSAGE = [
    "AssertionError: expected 404 to be less than 400",
    "    at /tmp/work/p1/v1/apps/api/src/__tests__/US-2.criteria.test.ts:37:33",
    "    at processTicksAndRejections (node:internal/process/task_queues:105:5)",
  ].join("\n");

  function failing(): TestSnapshot {
    const snapshot = buildTestSnapshot("p1", "awaiting", 1);
    return {
      ...snapshot,
      target: "generated",
      heal: null,
      healDecisions: [],
      tests: snapshot.tests && {
        ...snapshot.tests,
        target: "the generated app at code version 1",
        suites: [
          {
            path: "apps/api/src/__tests__/US-2.criteria.test.ts",
            framework: "vitest",
            cases: [
              {
                id: "c1",
                name: "As a receptionist, I can record a doctor US-2 AC-2-1: given no doctor, when one is saved, then it is retrievable",
                outcome: "failed",
                message: MESSAGE,
                traces: { storyId: "US-2", criterionId: "AC-2-1", requirementIds: ["R-1", "R-21", "R-27"] },
              },
            ],
          },
        ],
      },
    } as TestSnapshot;
  }

  const [failure] = buildView({ data: failing(), reviewer: "you" }).failures;

  it("is what the runner said, without the stack", () => {
    expect(failure.message).toBe("AssertionError: expected 404 to be less than 400");
  });

  it("still says why nothing classified it, apart from that", () => {
    expect(failure.triage).toBe("unclassified");
    expect(failure.reason).toMatch(/No earlier tested version to compare with/);
    expect(failure.reason).not.toMatch(/expected 404/);
  });

  it("names the line it failed at, so the file opens there", () => {
    expect(failure.line).toBe(37);
  });

  it("names every requirement the test protects, not the first", () => {
    expect(failure.requirements).toEqual(["R-1", "R-21", "R-27"]);
  });

  it("carries its reference apart from its story and its criterion", () => {
    expect(failure.label).toEqual({
      ref: "US-2 AC-2-1",
      story: "As a receptionist, I can record a doctor",
      text: "given no doctor, when one is saved, then it is retrievable",
    });
  });

  it("is held for the review by its reference, not its whole name", () => {
    expect(buildView({ data: failing(), reviewer: "you" }).failingRefs).toEqual(["US-2 AC-2-1"]);
  });
});

/**
 * What the run knew and the page did not say (the live clinic project,
 * 2026-10-13): five contract obligations nothing implements, under "Every
 * criterion in scope has a test"; and twelve npm audit advisories refused for
 * having no line in the repository, under "0 findings".
 */
describe("what was generated, and what could not be", () => {
  function generated(
    over: { gaps?: unknown[]; summary?: string } = {},
  ): TestSnapshot {
    const snapshot = buildTestSnapshot("p1", "awaiting", 1);
    const of = (id: string, origin: string, criterionId = "") => ({
      id,
      name: id,
      outcome: "passed",
      origin,
      traces: { storyId: criterionId ? "US-1" : null, criterionId },
    });
    return {
      ...snapshot,
      target: "generated",
      stages: {
        ...snapshot.stages,
        "test-generation": {
          ...snapshot.stages["test-generation"],
          summary: over.summary ?? "3 contract tests, 2 contract obligations nothing implements",
        },
      },
      tests: snapshot.tests && {
        ...snapshot.tests,
        gaps: over.gaps ?? [],
        suites: [
          {
            path: "apps/api/src/__tests__/US-1.criteria.test.ts",
            framework: "vitest",
            cases: [of("c1", "filled", "AC-1-1"), of("c2", "skeleton", "AC-1-2")],
          },
          {
            path: "apps/api/src/__tests__/records.oracle.test.ts",
            framework: "vitest",
            cases: [of("o1", "skeleton"), of("o2", "skeleton"), of("o3", "skeleton")],
          },
          {
            path: "apps/web/src/__tests__/routes.test.tsx",
            framework: "vitest",
            cases: [of("u1", "upstream")],
          },
        ],
      },
    } as TestSnapshot;
  }

  const GAP = {
    endpointId: "post-records-id-manage",
    kind: "no-way-to-create",
    detail: "the contract declares POST /records/{id}/manage and no POST on /records",
  };

  it("counts the tests by where they came from", () => {
    const view = buildView({ data: generated(), reviewer: "you" });

    expect(view.generation.sources).toEqual({ criteria: 2, filled: 1, contract: 3, shipped: 1 });
  });

  it("lists what the contract obliges and no test can assert", () => {
    const view = buildView({ data: generated({ gaps: [GAP] }), reviewer: "you" });

    expect(view.generation.gaps).toEqual([GAP]);
  });

  it("reads how many the stage reported, for a run made before they were listed", () => {
    const view = buildView({ data: generated(), reviewer: "you" });

    expect(view.generation.gaps).toEqual([]);
    expect(view.generation.gapsReported).toBe(2);
  });

  it("reports none where the stage reported none", () => {
    const view = buildView({ data: generated({ summary: "3 contract tests" }), reviewer: "you" });

    expect(view.generation.gapsReported).toBe(0);
  });

  it("carries what the stage said of itself", () => {
    expect(buildView({ data: generated(), reviewer: "you" }).generation.summary).toBe(
      "3 contract tests, 2 contract obligations nothing implements",
    );
  });
});

describe("the candidates a scan refused", () => {
  it("are listed with what was claimed and why each was refused", () => {
    const snapshot = buildTestSnapshot("p1", "awaiting", 1);
    const data = {
      ...snapshot,
      validation: snapshot.validation && {
        ...snapshot.validation,
        refusedEvidence: [
          {
            origin: "scanner",
            cwe: "CWE-22",
            reason: "no-evidence",
            claimedPath: "package.json",
            claimedStartLine: null,
            detail: "npm audit: Vitest: Path Traversal",
          },
        ],
      },
    } as TestSnapshot;

    expect(buildView({ data, reviewer: "you" }).refused).toEqual([
      {
        origin: "scanner",
        cwe: "CWE-22",
        reason: "no-evidence",
        path: "package.json",
        line: 0,
        detail: "npm audit: Vitest: Path Traversal",
      },
    ]);
  });

  it("are none before a scan", () => {
    expect(view("not-started").refused).toEqual([]);
  });
});

describe("coverage, file by file", () => {
  // Three files called index.ts in one list: the page showed the name alone.
  it("keeps each file's path beside its name", () => {
    const snapshot = buildTestSnapshot("p1", "awaiting", 1);
    const data = {
      ...snapshot,
      tests: snapshot.tests && {
        ...snapshot.tests,
        coverage: [
          {
            module: "apps/api/src/index.ts",
            linesCovered: 1,
            linesTotal: 10,
            branchesCovered: 0,
            branchesTotal: 0,
            linePercent: 10,
            branchPercent: 0,
          },
        ],
      },
    } as TestSnapshot;

    const [file] = buildView({ data, reviewer: "you" }).quality.byModule;

    expect(file.name).toBe("index.ts");
    expect(file.path).toBe("apps/api/src/index.ts");
  });
});

/** Who an audit entry's actor is: every author but "system" read as a person. */
describe("an audit entry's actor", () => {
  it("is told apart as an agent, a guard or a person", () => {
    expect(actorKindOf("Test agent")).toBe("agent");
    expect(actorKindOf("system")).toBe("agent");
    expect(actorKindOf("Honesty guard")).toBe("guard");
    expect(actorKindOf("Sampath Vinoshan")).toBe("human");
  });
});


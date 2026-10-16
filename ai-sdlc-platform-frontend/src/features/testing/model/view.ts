// One derivation for the whole phase, from the snapshot the server returns.
//
// Every count on the page comes from here, so the failing count in the suite
// table, the failure inbox, the summary strip and the final report can never
// disagree. What changed is where they come from: this used to derive from
// hand written demo data in a vocabulary of its own, and now derives from
// `TestSnapshot`, which is what both the fixtures and the orchestrator return.
//
// Three rules survived the move because they are about the phase rather than
// about the demo:
//
//   1. A decision belongs to a version. When a newer code version arrives, the
//      approval is superseded and the phase is waiting on a human again.
//   2. A refusal is a result. A repair the guard rejected is not a missing
//      repair; it is the most important row on the page.
//   3. Nothing is claimed that was not measured. A stage that did not run is
//      not a stage that passed, and mutation that did not run is not a score
//      of zero.
//
// What did not survive: the streaming transcript, the simulated re-run, and
// the client side decision state. The first two had no server counterpart and
// existed to animate a demo; the console now comes from the steps the harness
// really ran, exactly as the code phase builds its build log. The third moved
// to the server, where decisions are overlays with an author and a time.

import { transcriptOf, type ConsoleLine } from "@/shared/ui/console";
import { reviewIsOpen } from "@/shared/ui/phase/reviewIsOpen";
import { TEST_STAGE_IDS, type TestStageId } from "@/types/project";
import { TEST_STAGE_META } from "./stages";
import { firstLine, lineIn, shortTestName, testLabel, type TestLabel } from "./testName";
import type {
  FindingDecision,
  FixShipsWith,
  HealAttempt,
  RemediationProposal,
  Reverification,
  SecurityFinding,
  TestReport,
  TestSnapshot,
  ValidationReport,
} from "../api/types";
import type {
  AppliedFix,
  AuditEntry,
  FailureItem,
  Finding,
  Quality,
  Severity,
  SuiteModule,
  Triage,
} from "../fixtures/types";

/**
 * The stepper's ids are the server's stage ids.
 *
 * This phase used to keep six of its own over the contract's seven, so the
 * stepper and the stage table could disagree and one stage, test generation,
 * had nowhere on screen to report anything, including that it was skipped.
 * Every other gated phase keys its chrome on the contract's ids, and now so
 * does this one.
 */
export type StepId = TestStageId;

export type StepState = "done" | "attention" | "waiting" | "running" | "pending";

export type PhaseDecision = {
  kind: "approved" | "changes";
  at: string;
  by: string;
  build: number;
  note?: string;
};

/**
 * A person's verdict on one repair, as the page records it.
 *
 * The guard decides mechanically whether a repair may be accepted; this is
 * what a reader decides afterwards. The two are different facts about the same
 * repair and the study reports both, which is why this is not folded into the
 * attempt. It arrives from the server as an overlay once the read model
 * surfaces them, so it is optional rather than absent.
 */
export type RepairDecision = {
  decision: "approved" | "rejected";
  at: string;
  by: string;
  build: number;
};

/** A person's verdict on one security finding or its proposed fix. */
export type FindingAction =
  | { kind: "applied"; at: string; by: string }
  | { kind: "dismissed"; at: string; by: string };

/**
 * A failing generated test a person set aside: quarantined (skipped, with the
 * reason above it in the file, until restored) or sent back to be written again
 * (a test that never passed, back to a todo the next run fills).
 */
export type SetAside = {
  decision: "quarantined" | "rewrite";
  by: string;
  at: string;
  note: string;
};

export type ViewFailure = FailureItem & {
  /** The test's name taken apart, so a title can lead with "US-2 AC-2-1". */
  label?: TestLabel;
  /**
   * What the runner said when the test failed, without the stack. Apart from
   * `reason`, which is why the failure is classified as it is: on a first run
   * that reason is "nothing to compare with", and it stood where this goes.
   */
  message?: string;
  /** Every requirement the test protects; `requirement` is the first of them. */
  requirements?: string[];
  decision?: RepairDecision;
  setAside?: SetAside;
  /** Accepted by the guard, with no completed run yet pointing at the proof. */
  awaitingRerun?: boolean;
  /**
   * An API test, which every run writes again from the contract: a repair to
   * it would not outlast the next run, so the server refuses to keep one.
   */
  rewrittenEachRun?: boolean;
};

/** A contract obligation no test can assert, and why. */
export type GenerationGap = { endpointId: string; kind: string; detail: string };

/**
 * What the generation stage produced, read off the report and the stage.
 *
 * The step read the run's totals and nothing the generator said, so over five
 * contract obligations nothing implements it read "Every criterion in scope
 * has a test".
 */
export type Generation = {
  /** What the stage said of itself, as the server wrote it. */
  summary: string;
  /**
   * Where the suite's tests came from: written for an acceptance criterion
   * (and how many of those the model wrote), written by rule from the API
   * contract, or shipped with the code by Code Generation.
   */
  sources: { criteria: number; filled: number; contract: number; shipped: number };
  gaps: GenerationGap[];
  /**
   * How many the stage reported in its summary. A report made before the gaps
   * were kept on it lists none, and the summary is then the only place the
   * number is; saying "none" there would be the claim this field is for.
   */
  gapsReported: number;
};

/** A candidate the scan threw away, with what it claimed and why it was refused. */
export type RefusedCandidate = {
  origin: string;
  cwe: string;
  reason: string;
  path: string;
  line: number;
  detail: string;
};

/** A test that still runs, but no longer tests the build, and why. */
export type ObsoleteTest = { id: string; name: string; module: string; reason: string };

export type ViewInput = {
  data: TestSnapshot;
  reviewer: string;
};

export type TestingView = {
  /** This phase's own version counter. Zero before the first run. */
  build: number;
  finishedAt: string;
  duration: string;
  modules: SuiteModule[];
  /** Tests written for a story or criterion the build no longer has (C3-10). */
  obsolete: ObsoleteTest[];
  totals: { passed: number; failed: number; skipped: number; run: number; passRate: number };
  transcript: ConsoleLine[];
  transcriptTotal: number;
  /** A stage is working. Not a stream: the console arrives when a stage ends. */
  streaming: boolean;
  failures: ViewFailure[];
  inbox: {
    regressions: number;
    /** Failing, and not yet called a stale test or a regression. */
    unclassified: number;
    brittle: number;
    healed: number;
    awaiting: number;
    needsAttention: number;
  };
  awaitingRerun: number;
  quality: Quality;
  findings: Finding[];
  fixes: AppliedFix[];
  findingCounts: {
    open: number;
    proposed: number;
    applied: number;
    verified: number;
    dismissed: number;
    toResolve: number;
  };
  decisions: { approved: number; rejected: number; applied: number; dismissed: number };
  audit: AuditEntry[];
  steps: Record<StepId, { state: StepState; count?: number; hint: string }>;
  progress: number;
  decision: PhaseDecision | null;
  /** A decision made against an earlier version, now superseded. */
  superseded: PhaseDecision | null;
  decisionPending: boolean;
  /**
   * A review is waiting, but on code the project has since moved past: it is
   * not offered for deciding, and running the tests again closes it (the
   * server's `close_stale_review`).
   */
  reviewMovedPast: boolean;
  /**
   * The generated app's tests that failed in this run, by name. The server
   * refuses an approval while there are any, because Deployment's staging
   * build runs the same tests and refuses the candidate; a sample's failures
   * are seeded on purpose, so a sample lists none.
   */
  failingTests: string[];
  /** The same tests by reference ("US-2 AC-2-1"), for a line with room for a few words. */
  failingRefs: string[];
  /**
   * What this run did not prove, which approving over needs a note for, worded
   * as the server words it: no test ran, an app produced no report, criteria
   * declared and not written. Only a failure held an approval up, so a run in
   * which nothing ran read as "every proof passed".
   */
  unproven: string[];
  /** The test run stage's own summary, which says why nothing ran when nothing did. */
  runSummary: string | null;
  /**
   * What a fix applied now ships with, when it goes into newer code than may
   * ship today (review item C4-13), or null when a fix ships on its own.
   */
  fixShipsWith: string | null;
  /**
   * Why no other fix can be applied yet: the fix that wrote the current code
   * version, until a run measures it (review item C3-9). Null when one can.
   */
  fixAwaitingItsRun: string | null;
  /** Each scanning tool's outcome, as the Security step lists it (review item C3-5). */
  scanTools: string[];
  /** What the generation stage wrote and could not, as the Test Generation step says it. */
  generation: Generation;
  /** The candidates the scan refused, which are counted and never findings. */
  refused: RefusedCandidate[];
};

/**
 * The stepper, in the order a reader walks it.
 *
 * Derived from the contract's ids and the chrome's labels rather than written
 * out, because a list written out here is a second place for the order to live
 * and it drifted from the server's once already.
 */
export const stepOrder: { id: StepId; label: string }[] = TEST_STAGE_IDS.map((id) => ({
  id,
  label: TEST_STAGE_META[id].label,
}));

/**
 * Whether a test report measured the generated application.
 *
 * The component names what a report measured ("the generated app at code
 * version N", "the java sample", "a benchmark checkout at ..."), and that is the
 * orchestrator's rule too. A report not named that way, as the demo's are, says
 * nothing either way, so the target choice decides as it did before.
 */
export function measuredTheGeneratedApp(
  report: { target: string } | null | undefined,
  selectedTarget: string,
): boolean {
  const named = report?.target ?? "";
  if (named.startsWith("the generated app")) return true;
  if (/^the .+ sample$/.test(named) || named.startsWith("a benchmark checkout at ")) return false;
  return selectedTarget === "generated";
}

export function fileName(path: string) {
  return path.split("/").pop() ?? path;
}

/** src/main/java/com/payflow/user/UserRepository.java → user/UserRepository.java */
export function shortPath(path: string) {
  const parts = path.split("/");
  return parts.slice(-2).join("/");
}

/**
 * "file.test.ts:12", or the path alone when the line is not known.
 *
 * A live failure carries no line, so every link read "file.test.ts:0", a line
 * no file has.
 */
export function atLine(path: string, line: number | null | undefined): string {
  return line && line > 0 ? `${path}:${line}` : path;
}

/** "1 finding", "3 findings": the pages said "1 findings" and "1 repairs". */
export function counted(count: number, one: string, many: string): string {
  return `${count} ${count === 1 ? one : many}`;
}

/* ---------------------------------------------------------------- suites */

/** How many of something the report lists, or the count the demo writes. */
function countOf(value: unknown): number {
  return Array.isArray(value) ? value.length : Number(value ?? 0);
}

export function runnerOf(framework: string): SuiteModule["runner"] {
  return framework.toLowerCase().startsWith("junit") ? "JUnit 5" : "Vitest";
}

function sideOf(path: string): SuiteModule["side"] {
  return path.includes("/api/") || path.includes("src/test/java") ? "backend" : "frontend";
}

function secondsLabel(seconds: number): string {
  if (seconds >= 60) return `${Math.floor(seconds / 60)}m ${Math.round(seconds % 60)}s`;
  return `${seconds.toFixed(seconds < 10 ? 1 : 0)}s`;
}

function modulesFrom(tests: TestReport | null): SuiteModule[] {
  if (!tests) return [];
  return tests.suites.map((suite) => {
    const cases = suite.cases;
    const failed = cases.filter((one) => one.outcome === "failed");
    return {
      id: suite.path,
      name: fileName(suite.path),
      side: sideOf(suite.path),
      runner: runnerOf(suite.framework),
      passed: cases.filter((one) => one.outcome === "passed").length,
      failed: failed.length,
      skipped: cases.filter((one) => one.outcome === "skipped").length,
      duration: secondsLabel(
        cases.reduce((sum, one) => sum + Number(one.durationSeconds ?? 0), 0),
      ),
      // Every requirement any case in this file traces to, deduplicated. The
      // traceability chip reads this, and a file covering two requirements
      // should say both rather than the first.
      requirements: [
        ...new Set(cases.flatMap((one) => one.traces?.requirementIds ?? [])),
      ] as string[],
      failureIds: failed.map((one) => one.id),
      // Only what was recorded: a report stored before the first run's version
      // was kept on each case says neither.
      fresh: cases.filter((one) => one.sinceVersion && one.sinceVersion === tests.version).length,
      carried: cases.filter((one) => one.sinceVersion && one.sinceVersion < tests.version).length,
    };
  });
}

function obsoleteFrom(tests: TestReport | null): ObsoleteTest[] {
  if (!tests) return [];
  return tests.suites.flatMap((suite) =>
    suite.cases
      .filter((one) => one.obsolete)
      .map((one) => ({
        id: one.id,
        name: one.name,
        module: fileName(suite.path),
        reason: one.obsolete,
      })),
  );
}

/* -------------------------------------------------------------- failures */

const TRIAGE: Record<string, Triage> = {
  brittle: "brittle",
  regression: "regression",
  // Undecided is not a regression: the classifier could not tell, and a person
  // decides. Filed as one, it sent readers to change code that may be right.
  undecided: "unclassified",
};

/** Why a failure has no classification, when the heal report has nothing on it. */
const NO_EARLIER_VERSION =
  "No earlier tested version to compare with, so nothing yet tells a stale test from a regression.";

/**
 * Why this failure is what the healing loop called it, in the reader's words.
 *
 * The evidence is on the attempt, so this restates it rather than inventing a
 * reason. A classification with no citable evidence says so: an undecided
 * failure reaches a person precisely because the machine could not justify a
 * verdict, and dressing that up would hide the one case that needs a human.
 */
function reasonFor(attempt: HealAttempt | undefined, message: string): string {
  if (!attempt) return message || "No classification was recorded for this failure.";
  if (attempt.classification === "undecided") {
    return (
      attempt.evidence?.refereeReasoning ||
      "The classifier could not tell whether the test or the code is wrong, so a person decides."
    );
  }
  if (attempt.classification === "regression") {
    return "The artefacts this test traces to did not change, so the test is right and the code is not.";
  }
  if (attempt.evidence?.citedDiffSpan) {
    return `The behaviour changed on purpose: ${attempt.evidence.citedDiffSpan}`;
  }
  if (attempt.evidence?.refereeReasoning) return attempt.evidence.refereeReasoning;
  return message || "Classified without a citable change.";
}

function stateFor(attempt: HealAttempt | undefined): FailureItem["state"] {
  if (!attempt) return "escalated";
  if (attempt.accepted) return "healed";
  if (attempt.classification === "regression") return "escalated";
  // Refused by the guard. Blocked rather than escalated: a person is being
  // shown a repair that was produced and rejected, with the diff.
  return attempt.refusalReason ? "blocked" : "awaiting-approval";
}

function failuresFrom(
  tests: TestReport | null,
  heal: TestSnapshot["heal"],
  decisions: TestSnapshot["healDecisions"] | undefined,
): ViewFailure[] {
  if (!tests) return [];
  const attempts = new Map((heal?.attempts ?? []).map((one) => [one.testId, one]));
  // The reader's decision on each repair, as the server read it back. It was
  // recorded and never returned, so deciding changed nothing on the page.
  const decided = new Map(
    (decisions ?? [])
      .filter((one) => one.decision === "kept" || one.decision === "reverted")
      .map((one) => [
        one.testId,
        {
          decision: one.decision === "kept" ? ("approved" as const) : ("rejected" as const),
          at: one.at,
          by: one.by,
          build: tests.version,
        },
      ]),
  );
  // A failing test set aside by a person, which a repair decision is not.
  const setAside = new Map(
    (decisions ?? []).flatMap((one) =>
      one.decision === "quarantined" || one.decision === "rewrite"
        ? [[one.testId, { decision: one.decision, by: one.by, at: one.at, note: one.note }] as const]
        : [],
    ),
  );

  // A quarantined test stays listed after the runs that skip it, or nobody
  // could find it to restore it.
  const failed = tests.suites.flatMap((suite) =>
    suite.cases
      .filter(
        (one) =>
          one.outcome === "failed" ||
          (one.outcome === "skipped" && setAside.get(one.id)?.decision === "quarantined"),
      )
      .map((one) => ({ suite, one })),
  );
  // What each measured test exercises, for the attempts reached through the
  // heal report rather than through a failing case.
  const kinds = new Map(
    tests.suites.flatMap((suite) => suite.cases.map((one) => [one.id, one.kind] as const)),
  );

  // Every attempt the loop made that is not already in the failing list.
  //
  // Not only the accepted ones, which is what this did at first and what the
  // tests caught. A healed test passes in the report that followed its repair,
  // so it is not red any more; a refused repair leaves its test failing in the
  // run that produced the report, but a report taken afterwards need not carry
  // it either; and a flagged regression may be in neither. Filtering to
  // accepted attempts dropped exactly the two rows this phase exists to show,
  // which is the opposite of "a refusal is a result".
  const unlisted = (heal?.attempts ?? []).filter(
    (attempt) => !failed.some(({ one }) => one.id === attempt.testId),
  );

  const fromCases: ViewFailure[] = failed.map(({ suite, one }) => {
    const attempt = attempts.get(one.id);
    const aside = setAside.get(one.id);
    return {
      id: one.id,
      test: one.name,
      label: testLabel(one.name),
      message: firstLine(one.message),
      requirements: one.traces?.requirementIds ?? [],
      moduleId: suite.path,
      runner: runnerOf(suite.framework),
      triage: attempt ? (TRIAGE[attempt.classification] ?? "regression") : "unclassified",
      state: aside?.decision === "quarantined" ? "quarantined" : stateFor(attempt),
      reason: attempt || heal ? reasonFor(attempt, one.message ?? "") : NO_EARLIER_VERSION,
      age: "",
      at: tests.generatedAt,
      build: tests.version,
      requirement: {
        id: one.traces?.requirementIds?.[0] ?? "",
        title: one.traces?.storyId ?? "",
      },
      file: suite.path,
      // Where the runner's stack passes through the test file, so the file
      // opens at the assertion that failed; it opened at the top.
      line: lineIn(one.message, suite.path),
      repair: repairOf(attempt, suite.path, tests.generatedAt),
      awaitingRerun: Boolean(attempt?.accepted && !attempt.passedOnUnchangedRunId),
      rewrittenEachRun: one.kind === "api",
      decision: decided.get(one.id),
      setAside: aside,
    };
  });

  const fromHeals: ViewFailure[] = unlisted.map((attempt) => ({
    id: attempt.testId,
    test: attempt.testName,
    label: testLabel(attempt.testName),
    message: firstLine(attempt.failureMessage),
    requirements: attempt.evidence?.tracedTo ?? [],
    moduleId: attempt.suitePath,
    runner: runnerOf(attempt.suitePath.endsWith(".java") ? "junit5" : "vitest"),
    triage: attempt.accepted ? "healed" : (TRIAGE[attempt.classification] ?? "regression"),
    state: stateFor(attempt),
    reason: reasonFor(attempt, attempt.failureMessage ?? ""),
    age: "",
    at: heal?.generatedAt ?? "",
    build: heal?.version ?? 0,
    requirement: { id: attempt.evidence?.tracedTo?.[0] ?? "", title: "" },
    file: attempt.suitePath,
    line: lineIn(attempt.failureMessage, attempt.suitePath),
    repair: repairOf(attempt, attempt.suitePath, heal?.generatedAt ?? ""),
    awaitingRerun: Boolean(attempt.accepted && !attempt.passedOnUnchangedRunId),
    rewrittenEachRun: kinds.get(attempt.testId) === "api",
    decision: decided.get(attempt.testId),
  }));

  return [...fromCases, ...fromHeals];
}

/**
 * The proposed change and the guard's verdict on it, for a reader to judge.
 *
 * One builder for both paths into the inbox. A refused repair reached through
 * the failing case and the same repair reached through the heal report are the
 * same repair, and two constructions of it would eventually disagree about
 * which one shows the diff.
 */
function repairOf(attempt: HealAttempt | undefined, path: string, at: string) {
  if (!attempt?.diff) return undefined;
  return {
    proposedAt: at,
    path,
    language: (path.endsWith(".java") ? "java" : "tsx") as "java" | "tsx",
    original: "",
    proposed: attempt.diff.diff,
    guard: {
      unchanged: guardCheck(attempt, "passes-unchanged-code"),
      planted: guardCheck(attempt, "kills-a-mutant"),
    },
    verdictLine: attempt.accepted
      ? "Accepted: it changes tests only, still passes, and still kills a mutant."
      : `Refused: ${attempt.refusalReason ?? "the guard did not accept it"}.`,
    why: reasonFor(attempt, attempt.failureMessage ?? ""),
  };
}

function guardCheck(attempt: HealAttempt, name: string) {
  const check = attempt.checks?.find((one) => one.name === name);
  return { pass: Boolean(check?.passed), detail: check?.detail ?? "not checked" };
}

/* -------------------------------------------------------------- findings */

const STATUS: Record<string, Finding["status"]> = {
  open: "open",
  dismissed: "dismissed",
  accepted: "open",
  resolved: "verified",
};

function detectorsOf(finding: SecurityFinding): Finding["foundBy"] {
  // The report's vocabulary is scanner, llm and trained; the page's is local
  // and reviewer. Mapped rather than renamed, because the page's words are
  // what a reader outside this project understands.
  const arms = new Set(finding.raisedBy as string[]);
  const found: Finding["foundBy"] = [];
  if (arms.has("scanner") || arms.has("trained")) found.push("local");
  if (arms.has("llm")) found.push("reviewer");
  return found.length ? found : ["local"];
}

/**
 * Each finding with the fix proposed for it.
 *
 * The two arrive apart, findings in the validation report and fixes in the
 * remediation artefact, and the page never joined them: every finding opened
 * to an empty box, and Apply fix, Dismiss and the re-verification behind them
 * could not be reached.
 */
function findingsFrom(
  validation: ValidationReport | null,
  proposals: RemediationProposal[],
  decisions: FindingDecision[],
): Finding[] {
  if (!validation) return [];
  // A risk accepted with a reason, which the release gate reads (G8).
  const accepted = new Map(
    decisions
      .filter((one) => one.decision === "accepted" && one.note.trim())
      .map((one) => [one.findingId, one.note]),
  );
  // The first proposal for a finding is this scan's: the server lists the
  // current proposals before fixes carried from earlier versions.
  const byFinding = new Map<string, RemediationProposal>();
  for (const one of proposals) {
    if (!byFinding.has(one.findingId)) byFinding.set(one.findingId, one);
  }
  return validation.findings.map((finding) => {
    const proposal = byFinding.get(finding.id);
    return {
      id: finding.id,
      cwe: finding.cwe,
      name: finding.title,
      severity: (finding.severity ?? "medium") as Severity,
      cvss: Number(finding.baseScore ?? 0),
      file: finding.evidence.path,
      line: Number(finding.evidence.startLine),
      status: statusOf(finding, proposal),
      foundBy: detectorsOf(finding),
      explanation: finding.explanation || finding.severityReasoning || "",
      proposal: proposal
        ? {
            id: proposal.id,
            summary: proposal.summary,
            hunks: proposal.patch,
            state: proposal.state,
            risk: proposal.risk.statement,
            appliedCodeVersion: proposal.appliedCodeVersion ?? null,
          }
        : undefined,
      riskAccepted: accepted.get(finding.id),
    };
  });
}

/**
 * Where a finding stands, from the report and then from its fix.
 *
 * A dismissal or a resolution in the report wins. Otherwise the fix says it:
 * a weakness whose fix was dismissed or rolled back is as open as it was.
 */
function statusOf(
  finding: SecurityFinding,
  proposal: RemediationProposal | undefined,
): Finding["status"] {
  const reported = STATUS[finding.status] ?? "open";
  if (reported !== "open" || !proposal) return reported;
  if (proposal.state === "verified") return "verified";
  if (proposal.state === "applied") return "fix-applied";
  if (proposal.state === "proposed" || proposal.state === "accepted") return "fix-proposed";
  return "open";
}

/* ------------------------------------------------------------------ fixes */

function fixesFrom(snapshot: TestSnapshot): AppliedFix[] {
  const proposals = snapshot.remediation?.proposals ?? [];
  return proposals.map((proposal) => {
    const verification = proposal.reverification;
    const base = {
      findingId: proposal.findingId,
      appliedBy: proposal.decidedBy || "",
      appliedAt: proposal.decidedAt ?? proposal.generatedAt,
    };
    // A proposal nobody has applied has nothing to prove yet, which is pending
    // rather than failing.
    if (!verification) {
      return {
        ...base,
        scan: { state: "pending" as const, detail: "Starts when the fix is applied", at: undefined },
        suite: { state: "pending" as const, detail: "Starts when the re-scan finishes", at: undefined },
        verdict:
          proposal.state === "proposed"
            ? "Waiting on your decision."
            : "Accepted. Applying goes through code generation.",
      };
    }
    const broke = verification.testsBroken;
    const suite = {
      state: broke > 0 ? ("fail" as const) : ("pass" as const),
      detail: broke > 0 ? `${broke} test${broke === 1 ? "" : "s"} broke` : "no test broke",
      at: undefined,
    };
    // A comparison recorded before it looked for the finding counted totals
    // only, which proves nothing about this one, so it is asked again.
    if (!verification.findingId) {
      return {
        ...base,
        scan: { state: "pending" as const, detail: "Counted totals only", at: undefined },
        suite,
        verdict: reverificationVerdict(verification),
        pendingNote:
          "Re-verifying compares the same two runs again, and looks for the finding itself in the scan after the fix.",
      };
    }
    // The scan passes only when the finding this fix was for is gone, and
    // nothing new took its place: the verdicts are computed on the contract.
    const rose = verification.after.openFindings > verification.before.openFindings;
    return {
      ...base,
      scan: {
        state: verification.findingClosed && !rose ? ("pass" as const) : ("fail" as const),
        detail: !verification.findingClosed
          ? "The finding is still raised after the fix"
          : rose
            ? `The finding it was for is gone, but open findings rose from ${verification.before.openFindings} to ${verification.after.openFindings}`
            : "The finding it was for is gone",
        at: undefined,
      },
      suite,
      verdict: reverificationVerdict(verification),
    };
  });
}

/**
 * Why a re-verification did not verify its fix, as a clause, or null when it did.
 *
 * From the contract's computed fields: totals that held called a fix verified
 * with its own finding still raised (review item C3-7).
 */
function notVerifiedBecause(verification: Reverification): string | null {
  if (!verification.findingId) {
    return "this comparison counted totals only and did not look for the finding itself";
  }
  if (verification.worsened) {
    const broke = verification.testsBroken;
    return broke > 0
      ? `${broke} test${broke === 1 ? "" : "s"} broke, so a rollback is offered`
      : `open findings rose from ${verification.before.openFindings} to ${verification.after.openFindings}, so a rollback is offered`;
  }
  if (!verification.findingClosed) {
    return "the scan still raises the finding this fix was for, so it did not close it";
  }
  return null;
}

/** What a re-verification says about its fix, as the page words it. */
export function reverificationVerdict(verification: Reverification): string {
  if (!verification.findingId) {
    return "This comparison counted totals only and did not look for the finding itself: re-verify to check it.";
  }
  const because = notVerifiedBecause(verification);
  return because ? `Not verified: ${because}.` : "Fixed and re-verified.";
}

/** The toast a re-verification answers with, in the same words. */
export function reverifiedToast(verification: Reverification): {
  type: "success" | "error";
  title: string;
  message: string;
} {
  const because = notVerifiedBecause(verification);
  return because === null
    ? { type: "success", title: "Re-verified", message: "The finding it was for is gone, and no test broke." }
    : { type: "error", title: "Not verified", message: `${because.charAt(0).toUpperCase()}${because.slice(1)}.` };
}

/* ---------------------------------------------------------------- quality */

/** A mutator's change in words: Stryker's names for TypeScript, PIT's for Java. */
const MUTATOR_WORDS: Record<string, string> = {
  ArithmeticOperator: "an arithmetic operator was swapped",
  ArrayDeclaration: "an array was emptied",
  ArrowFunction: "a function was made to return nothing",
  AssignmentOperator: "an assignment operator was swapped",
  BlockStatement: "a block was emptied",
  BooleanLiteral: "true and false were swapped",
  ConditionalExpression: "a condition was forced true or false",
  EqualityOperator: "a comparison was swapped",
  LogicalOperator: "a logical operator was swapped",
  MethodExpression: "a method call was swapped",
  ObjectLiteral: "an object was emptied",
  OptionalChaining: "an optional access was made required",
  Regex: "a regular expression was changed",
  StringLiteral: "a string was emptied",
  UnaryOperator: "a unary operator was swapped",
  UpdateOperator: "an increment was swapped",
  CONDITIONALS_BOUNDARY: "a comparison's boundary moved",
  NEGATE_CONDITIONALS: "a condition was negated",
  MATH: "an arithmetic operator was swapped",
  INCREMENTS: "an increment was swapped",
  VOID_METHOD_CALLS: "a method call was removed",
  RETURN_VALS: "a return value was changed",
  EMPTY_RETURNS: "a return value was emptied",
  NULL_RETURNS: "a return value became null",
  PRIMITIVE_RETURNS: "a returned number became zero",
  TRUE_RETURNS: "a returned boolean became true",
  FALSE_RETURNS: "a returned boolean became false",
};

/** "apps/web/src/format.ts:12:5:ArithmeticOperator", as a reader would say it. */
export function survivorFrom(id: string): { location: string; change: string; note: string } {
  const parts = id.split(":");
  const mutator = parts.length >= 4 ? parts[parts.length - 1] : "";
  const line = parts.length >= 4 ? parts[parts.length - 3] : "";
  const path = parts.length >= 4 ? parts.slice(0, parts.length - 3).join(":") : id;
  const change =
    MUTATOR_WORDS[mutator] ?? (mutator ? `${mutator.replace(/_/g, " ").toLowerCase()} was planted` : "a change was planted");
  return {
    location: line ? `${fileName(path)}:${line}` : fileName(path),
    change,
    note: "No test noticed.",
  };
}

function qualityFrom(tests: TestReport | null): Quality {
  const coverage = tests?.coverage ?? [];
  const sum = (pick: (entry: (typeof coverage)[number]) => number) =>
    coverage.reduce((total, one) => total + Number(pick(one)), 0);
  const mutation = tests?.mutation ?? null;

  return {
    line: {
      percent: Number(tests?.lineCoverage ?? 0),
      covered: sum((one) => one.linesCovered),
      total: sum((one) => one.linesTotal),
    },
    branch: {
      percent: Number(tests?.branchCoverage ?? 0),
      covered: sum((one) => one.branchesCovered),
      total: sum((one) => one.branchesTotal),
    },
    mutation: {
      total: Number(mutation?.total ?? 0),
      // The contract lists the mutants by id, so a survivor keeps its address.
      // `Number` of a list is NaN, which is what live pages showed ("NaN
      // killed · NaN survived"); the demo's numbers are counted as they are.
      killed: countOf(mutation?.killed),
      survived: countOf(mutation?.survived),
      score: Number(mutation?.score ?? 0),
    },
    tool: mutation?.tool ?? "",
    byModule: coverage.map((one) => ({
      name: fileName(one.module),
      path: one.module,
      line: Number(one.linePercent),
      branch: Number(one.branchPercent),
      branches: Number(one.branchesTotal),
      covered: Number(one.linesCovered),
      total: Number(one.linesTotal),
    })),
    // Each surviving mutant, from its address in the report. The panel listed
    // the quality checks' findings under "What survived" and sent the rest to
    // "the full mutation report", which nothing produces.
    // A list of ids live; the demo carries a count, which names no one.
    survivors: Array.isArray(mutation?.survived) ? mutation.survived.map(survivorFrom) : [],
    findings: (tests?.quality ?? []).map((finding) => ({
      location: finding.test,
      change: finding.rule,
      note: finding.detail,
    })),
    mutationRan: mutation !== null,
    mutationSkippedReason: tests?.mutationSkippedReason || "Mutation did not run.",
    mutationNotMeasured: mutation?.notMeasured ?? [],
    trend: tests ? [{ build: tests.version, line: Number(tests.lineCoverage), branch: Number(tests.branchCoverage) }] : [],
    // Counted: the contract lists the mutants by id, and a list in a template
    // printed every id ("a:1:1,b:2:1 of 2 mutants killed").
    trendNote: mutation
      ? `${countOf(mutation.killed)} of ${Number(mutation.total)} mutants killed`
      : tests?.mutationSkippedReason || "Mutation did not run.",
  };
}

/**
 * The mutation score as a tile shows it: a percentage only when mutation ran,
 * and which app gave no score when only part of the scope did. The summary
 * strip and the report showed "0%" for a run that never happened (C3-6).
 */
export function mutationTile(quality: Quality): { value: string; note: string } {
  if (quality.mutationRan === false) return { value: "Not measured", note: "mutation did not run" };
  const counts = `${quality.mutation.killed} killed · ${quality.mutation.survived} survived`;
  const apps = (quality.mutationNotMeasured ?? []).map((one) => one.app);
  return {
    value: `${quality.mutation.score}%`,
    note: apps.length > 0 ? `${counts} · ${apps.join(", ")} not measured` : counts,
  };
}

/* ------------------------------------------------------------------ audit */

/** Who acted, by kind: every author but "system" read as a person, the agents included. */
export function actorKindOf(actor: string): AuditEntry["actorKind"] {
  const named = actor.toLowerCase();
  if (named.includes("guard")) return "guard";
  if (named === "system" || named.endsWith(" agent") || named.startsWith("canned")) return "agent";
  return "human";
}

/**
 * This phase's entries in the audit log, newest first, as the server read them.
 *
 * It was the chat thread, labelled "every decision on this phase", which held
 * few of them. The demo's snapshots carry no entries, so they keep the thread.
 */
function auditFrom(snapshot: TestSnapshot): AuditEntry[] {
  if (snapshot.audit) {
    return snapshot.audit.map((entry, index) => ({
      id: `${entry.at}-${index}`,
      at: entry.at,
      actor: entry.actor,
      actorKind: actorKindOf(entry.actor),
      action: entry.action,
      target: entry.target,
      detail: entry.detail,
    }));
  }
  return snapshot.thread.map((message) => ({
    id: message.id,
    at: message.at,
    actor: message.author,
    actorKind: actorKindOf(message.author),
    action: message.kind === "stage_summary" ? "Stage finished" : "Note",
    target: message.stageId ?? "",
    detail: message.content,
  }));
}

/* ------------------------------------------------------------------- view */

function stageStatus(snapshot: TestSnapshot, id: TestStageId) {
  return snapshot.stages[id]?.status ?? "pending";
}

/**
 * A stage that has not produced anything, and why.
 *
 * `pending` means not started yet and `skipped` means it will not start on this
 * target: test generation writes TypeScript from the API contract, so a Java
 * repository gives it nothing to write. Both render the same greyed step, and
 * the hint is what tells them apart, taken from what the server said rather
 * than invented here.
 */
function notRun(
  snapshot: TestSnapshot,
  id: TestStageId,
  waitingHint: string,
): { state: StepState; hint: string } | null {
  const status = stageStatus(snapshot, id);
  if (status === "skipped") {
    return { state: "pending", hint: snapshot.stages[id]?.summary || "does not apply here" };
  }
  if (status === "pending") return { state: "pending", hint: waitingHint };
  return null;
}

/**
 * What an approval's note says was left open.
 *
 * Every unresolved finding, as the gate's own audit entry counts them: one
 * whose fix is proposed or applied but not yet re-verified is still an open
 * weakness.
 */
export function approvalNote(view: Pick<TestingView, "findingCounts">): string {
  const open = view.findingCounts.toResolve;
  return `Approved with ${open} finding${open === 1 ? "" : "s"} open.`;
}

export function buildView(input: ViewInput): TestingView {
  const snapshot = input.data;
  const tests = snapshot.tests;
  const running = TEST_STAGE_IDS.some((id) => stageStatus(snapshot, id) === "generating");

  const modules = modulesFrom(tests);
  const failures = failuresFrom(tests, snapshot.heal, snapshot.healDecisions);
  const findings = findingsFrom(
    snapshot.validation,
    snapshot.remediation?.proposals ?? [],
    snapshot.findingDecisions ?? [],
  );
  const fixes = fixesFrom(snapshot);
  const quality = qualityFrom(tests);

  const passed = Number(tests?.passed ?? 0);
  const failed = Number(tests?.failed ?? 0);
  // What ran is what passed or failed. The report's total counts the skipped
  // ones too (a criterion nothing can observe is declared and not written), and
  // read as "run" it gave "24 of 27 run, pass rate 88.9%" with nothing failing.
  const run = passed + failed;
  const totals = {
    passed,
    failed,
    skipped: Number(tests?.skipped ?? 0),
    run,
    passRate: run === 0 ? 0 : (passed / run) * 100,
  };

  // A quarantined test is decided: it waits on nobody, though it stays listed.
  const open = failures.filter(
    (one) => one.triage !== "healed" && one.state !== "healed" && one.state !== "quarantined",
  );
  const inbox = {
    regressions: open.filter((one) => one.triage === "regression").length,
    unclassified: open.filter((one) => one.triage === "unclassified").length,
    brittle: open.filter((one) => one.triage === "brittle").length,
    healed: failures.filter((one) => one.state === "healed").length,
    awaiting: open.filter((one) => one.state === "awaiting-approval").length,
    needsAttention: open.length,
  };
  const awaitingRerun = failures.filter((one) => one.awaitingRerun).length;
  // What the run measured, as its report names it, not the newest choice:
  // the choice may change while a review waits, and reading it hid the
  // generated app's failures behind a switch to a sample.
  // A quarantined test does not hold up the review, as the server reads it:
  // it is skipped from here on, with its reason on the record.
  const quarantined = new Set(
    (snapshot.healDecisions ?? [])
      .filter((one) => one.decision === "quarantined")
      .map((one) => one.testId),
  );
  const failingTests =
    measuredTheGeneratedApp(tests, snapshot.target)
      ? (tests?.suites ?? []).flatMap((suite) =>
          suite.cases
            .filter(
              (one) =>
                (one.outcome === "failed" || one.outcome === "errored") && !quarantined.has(one.id),
            )
            .map((one) => one.name),
        )
      : [];

  const unproven =
    tests && measuredTheGeneratedApp(tests, snapshot.target) ? unprovenIn(tests, quarantined) : [];

  // Every count reads the finding's own status, so the distribution adds up
  // to the findings listed. A finding with a fix proposed or applied is not
  // resolved: only its re-verification or a dismissal resolves it.
  const countOf = (status: Finding["status"]) => findings.filter((one) => one.status === status).length;
  const findingCounts = {
    open: countOf("open"),
    proposed: countOf("fix-proposed"),
    applied: countOf("fix-applied"),
    verified: countOf("verified"),
    dismissed: countOf("dismissed"),
    toResolve: countOf("open") + countOf("fix-proposed") + countOf("fix-applied"),
  };

  const proposals = snapshot.remediation?.proposals ?? [];
  const decisions = {
    approved: (snapshot.heal?.attempts ?? []).filter((one) => one.accepted).length,
    rejected: Number(snapshot.heal?.refused ?? 0),
    applied: proposals.filter((one) => one.state !== "proposed" && one.state !== "dismissed").length,
    dismissed: findingCounts.dismissed,
  };

  // Rule 1: an approval covers the version it was given for, and nothing
  // later. The snapshot computes `codeMovedOn` from the two version numbers,
  // so a decision about an older build is visibly superseded rather than
  // silently standing.
  const gate = snapshot.gate.decision;
  const decided: PhaseDecision | null = gate
    ? {
        kind: gate.kind as PhaseDecision["kind"],
        at: gate.at,
        by: gate.by,
        build: Number(gate.version),
        note: gate.note || undefined,
      }
    : null;
  const current = decided && decided.build === snapshot.testVersion && !snapshot.codeMovedOn;
  const decisionForThisBuild = current ? decided : null;
  const superseded = decided && !current ? decided : null;
  // Live, the run says whether the review is open. A review of code that has
  // since moved on is not offered: requesting changes there is refused, and
  // running the tests again closes it. The demo keeps its own rule.
  const reviewWaits = snapshot.run
    ? reviewIsOpen(snapshot.run, snapshot.testVersion, () => false)
    : false;
  const reviewMovedPast = reviewWaits && snapshot.codeMovedOn;
  const decisionPending = snapshot.run
    ? reviewWaits && !snapshot.codeMovedOn
    : !running && snapshot.testVersion > 0 && decisionForThisBuild === null;

  const stepFor = (id: TestStageId) => stageStatus(snapshot, id);
  const steps: Record<StepId, { state: StepState; count?: number; hint: string }> = {
    "test-generation":
      stepFor("test-generation") === "generating"
        ? { state: "running", hint: "writing the tests" }
        : (notRun(snapshot, "test-generation", "not started") ?? {
            state: "done" as const,
            hint: totals.run > 0 ? `${totals.run} tests` : "nothing written",
          }),
    "test-run":
      stepFor("test-run") === "generating"
        ? { state: "running", hint: "running the suite" }
        : notRun(snapshot, "test-run", "not started")
          ? notRun(snapshot, "test-run", "not started")!
          : {
              state: totals.failed > 0 ? "attention" : "done",
              count: totals.failed || undefined,
              hint: totals.failed > 0 ? `${totals.failed} failing` : `${totals.passed} passing`,
            },
    "self-healing":
      stepFor("self-healing") === "generating"
        ? { state: "running", hint: "classifying and repairing" }
        : notRun(snapshot, "self-healing", "waits for the run")
          ? notRun(snapshot, "self-healing", "waits for the run")!
          : inbox.awaiting > 0
            ? { state: "waiting", count: inbox.awaiting, hint: `${inbox.awaiting} awaiting you` }
            : inbox.needsAttention > 0
              ? {
                  state: "attention",
                  count: inbox.needsAttention,
                  hint: `${inbox.needsAttention} need${inbox.needsAttention === 1 ? "s" : ""} a person`,
                }
              : { state: "done", hint: "nothing open" },
    "test-quality":
      stepFor("test-quality") === "generating"
        ? { state: "running", hint: "measuring mutants" }
        : notRun(snapshot, "test-quality", "waits for the run")
          ? notRun(snapshot, "test-quality", "waits for the run")!
          : {
              state: "done",
              hint: quality.mutationRan === false ? "mutation not measured" : `mutation score ${quality.mutation.score}%`,
            },
    "security-scan":
      stepFor("security-scan") === "generating"
        ? { state: "running", hint: "scanning" }
        : notRun(snapshot, "security-scan", "waits for the run")
          ? notRun(snapshot, "security-scan", "waits for the run")!
          : findingCounts.toResolve > 0
            ? {
                state: "attention",
                count: findingCounts.toResolve,
                hint: `${findingCounts.toResolve} to resolve`,
              }
            : { state: "done", hint: "nothing to resolve" },
    remediation:
      stepFor("remediation") === "generating"
        ? { state: "running", hint: "proposing fixes" }
        : stepFor("remediation") === "pending"
          ? { state: "pending", hint: "waits for the scan" }
          : fixes.length === 0
            ? { state: "pending", hint: "no fix proposed" }
            : fixes.some((one) => one.scan.state === "fail")
              ? { state: "attention", hint: "a fix made things worse" }
              : fixes.every((one) => one.scan.state === "pass")
                ? { state: "done", hint: `${fixes.length} verified` }
                : { state: "waiting", count: fixes.length, hint: `${fixes.length} awaiting you` },
    "test-review": decisionForThisBuild
      ? {
          state: "done",
          hint: decisionForThisBuild.kind === "approved" ? "approved" : "changes requested",
        }
      : running
        ? { state: "pending", hint: "waits for the run" }
        : { state: "waiting", hint: superseded ? "waiting on you again" : "waiting on you" },
  };

  // A step counts towards progress once it has nothing outstanding. Recording
  // the phase decision is the last of the six, so 100% means exactly that.
  const settled = Object.values(steps).filter((one) => one.state === "done").length;
  const progress = decisionForThisBuild
    ? 100
    : Math.round((settled / stepOrder.length) * 100);

  const transcript = transcriptOf(tests?.steps ?? []);
  const duration = tests
    ? secondsLabel(tests.steps.reduce((sum, one) => sum + Number(one.durationSeconds ?? 0), 0))
    : "";

  return {
    build: snapshot.testVersion,
    finishedAt: tests?.generatedAt ?? "",
    duration,
    modules,
    obsolete: obsoleteFrom(tests),
    totals,
    transcript,
    transcriptTotal: transcript.length,
    streaming: running,
    failures,
    inbox,
    awaitingRerun,
    quality,
    findings,
    fixes,
    findingCounts,
    decisions,
    audit: auditFrom(snapshot),
    steps,
    progress,
    decision: decisionForThisBuild,
    superseded,
    decisionPending,
    reviewMovedPast,
    failingTests,
    failingRefs: failingTests.map(shortTestName),
    unproven,
    runSummary: snapshot.stages["test-run"]?.summary ?? null,
    fixShipsWith: fixShipsWithLine(snapshot.fixShipsWith),
    fixAwaitingItsRun: fixAwaitingItsRunLine(snapshot),
    // A tool that never ran and one that found nothing look the same in an
    // empty list of findings, so each says which it was.
    scanTools: (snapshot.validation?.tools ?? []).map((one) =>
      one.ran ? `${one.tool}${one.version ? ` ${one.version}` : ""} ran` : `${one.tool} did not run: ${one.detail}`,
    ),
    generation: generationFrom(snapshot),
    refused: (snapshot.validation?.refusedEvidence ?? []).map((one) => ({
      origin: one.origin,
      cwe: one.cwe ?? "",
      reason: one.reason,
      path: one.claimedPath ?? "",
      line: one.claimedStartLine ?? 0,
      detail: one.detail ?? "",
    })),
  };
}

/** "5 contract obligations nothing implements", as the generation stage's summary counts them. */
const GAPS_REPORTED = /(\d+) contract obligations? nothing implements/;

function generationFrom(snapshot: TestSnapshot): Generation {
  const cases = (snapshot.tests?.suites ?? []).flatMap((suite) => suite.cases);
  const forCriterion = cases.filter((one) => one.traces?.criterionId);
  const summary = snapshot.stages["test-generation"]?.summary ?? "";
  return {
    summary,
    sources: {
      criteria: forCriterion.length,
      filled: forCriterion.filter((one) => one.origin === "filled").length,
      // Written by rule from the contract: this phase's, and for no criterion.
      contract: cases.filter((one) => one.origin === "skeleton" && !one.traces?.criterionId).length,
      shipped: cases.filter((one) => one.origin === "upstream").length,
    },
    // A fixture's report has no such field at all.
    gaps: (snapshot.tests?.gaps ?? []).map((one) => ({
      endpointId: one.endpointId,
      kind: one.kind,
      detail: one.detail,
    })),
    gapsReported: Number(GAPS_REPORTED.exec(summary)?.[1] ?? 0),
  };
}

/**
 * The fix that wrote the current code version, while no run has measured it,
 * as the page says it beside Apply fix.
 *
 * Testing runs only on the newest code, and re-verifying a fix needs a run at
 * exactly its version, so a second fix applied first left the first impossible
 * to re-verify. The server refuses it (review item C3-9); this says so before
 * the click. A fix newer code has passed holds nothing up: no run can measure
 * its version now.
 */
export function fixAwaitingItsRunLine(snapshot: TestSnapshot): string | null {
  const current = snapshot.codeVersion;
  if (snapshot.testedCodeVersion === current) return null;
  const waiting = snapshot.remediation?.proposals.find((one) => one.appliedCodeVersion === current);
  if (!waiting) return null;
  const where = waiting.patch[0]?.path;
  return `The ${waiting.cwe} fix${where ? ` in ${where}` : ""} is applied as code version ${current}, which no testing run has measured yet: run the tests on code version ${current} first, then apply another fix.`;
}

/**
 * Where a fix applied now lands, as the page says it beside Apply fix.
 *
 * A fix patches the newest code version, so code versions stay one line; over
 * newer code than may ship today it reaches production only with that code,
 * once its tests are approved. Nothing said so (review item C4-13).
 */
export function fixShipsWithLine(ships: FixShipsWith | null | undefined): string | null {
  if (!ships) return null;
  const { codeVersion, sprint, releasableCodeVersion, releasableSprint } = ships;
  return sprint > releasableSprint
    ? `A fix applied now goes into code version ${codeVersion}, sprint ${sprint}'s build, and reaches production with sprint ${sprint}, once its tests are approved. Code version ${releasableCodeVersion} (sprint ${releasableSprint}), the newest with approved tests, does not get it on its own.`
    : `A fix applied now goes into code version ${codeVersion}, the newest code, and reaches production with the rest of it, once its tests are approved. Code version ${releasableCodeVersion}, the newest with approved tests, does not get it on its own.`;
}

/** What to do about a review the code has moved past, as the page says it. */
export function reviewMovedPastLine(snapshot: TestSnapshot): string {
  return `This review is of code version ${snapshot.testedCodeVersion}, and the code is at version ${snapshot.codeVersion} now. Run the tests again to test version ${snapshot.codeVersion}: that closes this review.`;
}

/** An app's own run, as the harness names it when a repository has several. */
const APP_RUN = /^tests \((.+)\)$/;

const STEP_WORDS: Record<string, string> = {
  failed: "failed",
  "timed-out": "timed out",
  "not-run": "did not run",
};

/**
 * What a run of the generated app did not prove (`TestingView.unproven`). A
 * skipped generated test that nobody quarantined is a criterion still a todo:
 * nothing this platform writes skips a test of its own accord.
 */
export function unprovenIn(tests: TestReport, quarantined: Set<string>): string[] {
  const cases = tests.suites.flatMap((suite) => suite.cases);
  const concerns: string[] = [];
  const ran = cases.some(
    (one) => one.outcome === "passed" || one.outcome === "failed" || one.outcome === "errored",
  );
  if (!ran) {
    const stopped = tests.steps.find((step) => step.outcome !== "passed");
    concerns.push(
      stopped ? `no test ran: ${stopped.name} ${STEP_WORDS[stopped.outcome] ?? stopped.outcome}` : "no test ran",
    );
  } else {
    for (const step of tests.steps) {
      const app = APP_RUN.exec(step.name)?.[1];
      if (app && !tests.suites.some((suite) => suite.path.startsWith(`${app}/`))) {
        concerns.push(`${app} produced no test report`);
      }
    }
  }
  const unwritten = cases.filter((one) => one.outcome === "skipped" && !quarantined.has(one.id)).length;
  if (unwritten > 0) {
    concerns.push(
      `${unwritten} acceptance ${unwritten === 1 ? "criterion" : "criteria"} declared and not written`,
    );
  }
  return concerns;
}

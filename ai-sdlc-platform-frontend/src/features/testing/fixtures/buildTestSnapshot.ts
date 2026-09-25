import { TEST_STAGE_IDS, type TestStageId } from "@/types/project";
import type {
  HealReport,
  RemediationProposals,
  TestReport,
  TestSnapshot,
  TestStages,
  ValidationReport,
} from "../api/types";

/**
 * A whole testing phase, built for one project at one posture.
 *
 * Contract shaped, not fixture shaped. The old fixtures had a vocabulary of
 * their own and an HTTP client that called seven routes the orchestrator does
 * not have, so the demo worked and the live path could never have. Everything
 * here is the type the server really returns, which is what makes flipping the
 * flag a configuration change rather than a rewrite.
 *
 * The numbers are deliberately not round. A report showing 100 percent coverage
 * and no findings is a report nobody believes, and this phase's whole argument
 * is that it tells you what is wrong.
 */

/** How far through the testing phase a project is. */
export type TestPosture = "not-started" | "running" | "awaiting" | "approved";

const AT = "2026-09-20T09:00:00Z";

function stages(posture: TestPosture, version: number): TestStages {
  const state = (id: TestStageId, status: string, summary?: string) =>
    ({
      id,
      status,
      generatedFromVersion: status === "pending" ? 0 : version,
      generatedAt: status === "pending" ? null : AT,
      summary: summary ?? null,
      error: null,
    }) as TestStages[TestStageId];

  if (posture === "not-started") {
    return Object.fromEntries(TEST_STAGE_IDS.map((id) => [id, state(id, "pending")])) as TestStages;
  }
  if (posture === "running") {
    return {
      "test-generation": state("test-generation", "complete", "18 tests from 9 criteria"),
      "test-run": state("test-run", "generating"),
      "test-quality": state("test-quality", "pending"),
      "self-healing": state("self-healing", "pending"),
      "security-scan": state("security-scan", "pending"),
      remediation: state("remediation", "pending"),
      "test-review": state("test-review", "pending"),
    };
  }
  return {
    "test-generation": state("test-generation", "complete", "18 tests from 9 criteria"),
    "test-run": state("test-run", "complete", "17 passed, 1 failed"),
    "test-quality": state("test-quality", "complete", "mutation 61.4 percent, 2 weak fills"),
    "self-healing": state("self-healing", "complete", "1 healed, 1 refused, 1 regression flagged"),
    "security-scan": state("security-scan", "complete", "4 findings, 2 arms agreed on 1"),
    remediation: state("remediation", "complete", "2 fixes proposed, 1 could not be patched"),
    "test-review": state("test-review", "complete", "Ready for review"),
  };
}

/**
 * The computed fields the server derives and the wire type requires.
 *
 * Derived here too, from the same arrays, rather than written down beside
 * them. A fixture that states `passed: 17` over a list holding nine is a
 * fixture that teaches the UI to render a number the server would never send,
 * and the bug surfaces only when the flag flips.
 */
function countCases(suites: TestReport["suites"]) {
  const cases = suites.flatMap((suite) => suite.cases);
  const by = (outcome: string) => cases.filter((one) => one.outcome === outcome).length;
  return {
    total: cases.length,
    passed: by("passed"),
    failed: by("failed"),
    skipped: by("skipped"),
    notRun: by("not-run"),
    // Tests this platform wrote that say nothing about what they came from.
    // Derived for the same reason as the rest: it read every case for the life
    // of the run stage and nobody saw it, so a fixture that hardcoded zero
    // would teach the UI a state the server cannot be trusted to be in.
    untraced: cases.filter(
      (one) => one.origin !== "upstream" && !one.traces?.storyId && !one.traces?.criterionId,
    ).length,
  };
}

function withSuiteCounts(suites: TestReport["suites"]): TestReport["suites"] {
  return suites.map((suite) => {
    const by = (outcome: string) => suite.cases.filter((one) => one.outcome === outcome).length;
    return { ...suite, total: suite.cases.length, passed: by("passed"), failed: by("failed") };
  });
}

function testReport(version: number): TestReport {
  const report = {
    version,
    generatedAt: AT,
    target: "apps/web",
    isolation: "sandbox",
    steps: [
      { name: "install", command: "npm ci --ignore-scripts", outcome: "passed", durationMs: 8420 },
      { name: "vitest", command: "vitest run --coverage", outcome: "failed", durationMs: 3180 },
    ],
    suites: [
      {
        path: "apps/web/src/__tests__/basket.criteria.test.ts",
        framework: "vitest",
        cases: [
          {
            id: "basket::adds up the lines",
            name: "adds up the lines",
            outcome: "failed",
            kind: "unit",
            origin: "filled",
            durationSeconds: 0.01,
            message: "expected 3.01 to be 3.005",
            traces: { storyId: "US-2", criterionId: "AC-2-1", requirementIds: ["R-4"] },
          },
          {
            id: "basket::is zero when empty",
            name: "is zero when empty",
            outcome: "passed",
            kind: "unit",
            origin: "filled",
            durationSeconds: 0.01,
            traces: { storyId: "US-2", criterionId: "AC-2-2", requirementIds: ["R-4"] },
          },
        ],
      },
    ],
    coverage: [
      {
        module: "apps/web/src/basket.ts",
        linesCovered: 89,
        linesTotal: 103,
        linePercent: 86.4,
        branchesCovered: 27,
        branchesTotal: 38,
        branchPercent: 71.1,
      },
    ],
    mutation: {
      tool: "stryker",
      scope: "apps/web/src/basket.ts",
      killed: 27,
      survived: 17,
      inconclusive: 0,
      durationSeconds: 94.2,
    },
    quality: [
      {
        rule: "kills-no-mutant",
        testId: "basket::is zero when empty",
        detail: "the assertion holds for any program that returns a number",
      },
    ],
    mutationSkippedReason: "",
  };
  const counts = countCases(report.suites as TestReport["suites"]);
  const coverage = report.coverage;
  const weighted = (pick: (entry: (typeof coverage)[number]) => number) =>
    coverage.length
      ? Math.round((coverage.reduce((sum, one) => sum + pick(one), 0) / coverage.length) * 10) / 10
      : 0;
  return {
    ...report,
    suites: withSuiteCounts(report.suites as TestReport["suites"]),
    ...counts,
    lineCoverage: weighted((one) => one.linePercent),
    branchCoverage: weighted((one) => one.branchPercent),
    mutation: {
      ...report.mutation,
      total: report.mutation.killed + report.mutation.survived + report.mutation.inconclusive,
      score:
        Math.round(
          (report.mutation.killed /
            (report.mutation.killed + report.mutation.survived + report.mutation.inconclusive)) *
            1000,
        ) / 10,
    },
  } as unknown as TestReport;
}

function healReport(version: number): HealReport {
  const report = {
    version,
    generatedAt: AT,
    target: "apps/web",
    fromCodeVersion: version,
    toCodeVersion: version + 1,
    attempts: [
      {
        testId: "basket::adds up the lines",
        testName: "adds up the lines",
        suitePath: "apps/web/src/__tests__/basket.criteria.test.ts",
        failureMessage: "expected 3.01 to be 3.005",
        passedOnUnchangedRunId: "run-unchanged-1",
        classification: "brittle",
        classifiedBy: "trace-changed",
        evidence: {
          tracedTo: ["R-4"],
          changedArtefacts: ["R-4"],
          citedDiffSpan: "[R1] requirement R-4 changed its rounding from 3 to 2 decimals",
          refereeReasoning: "",
        },
        accepted: true,
        attempts: 1,
        rejectedDrafts: [],
        diff: {
          path: "apps/web/src/__tests__/basket.criteria.test.ts",
          diff:
            "@@\n-    expect(total([1.005, 2])).toBe(3.005);\n" +
            "+    expect(total([1.005, 2])).toBe(3.01);",
        },
        checks: [
          { name: "test-code-only", passed: true, detail: "one test file changed" },
          { name: "passes-unchanged-code", passed: true, detail: "the suite is green" },
          { name: "kills-a-mutant", passed: true, detail: "killed 2 of 3 injected mutants" },
        ],
        refusalReason: null,
        killedMutantIds: ["m-14", "m-19"],
      },
      {
        testId: "basket::applies the member discount",
        testName: "applies the member discount",
        suitePath: "apps/web/src/__tests__/basket.criteria.test.ts",
        failureMessage: "expected 4500 to be 4000",
        passedOnUnchangedRunId: "run-unchanged-1",
        classification: "brittle",
        classifiedBy: "model-referee",
        evidence: {
          tracedTo: ["R-7"],
          changedArtefacts: ["R-7"],
          citedDiffSpan: "[R2] requirement R-7 changed its threshold from 50 to 40",
          refereeReasoning: "the threshold moved on purpose, so the test encodes the old one",
        },
        accepted: false,
        attempts: 2,
        rejectedDrafts: [
          "refused: the repaired body asserts something that holds for any program\n" +
            "@@\n-    expect(discounted(5000, 10)).toBe(4500);\n" +
            "+    expect(discounted(5000, 10)).toBeDefined();",
        ],
        diff: {
          path: "apps/web/src/__tests__/basket.criteria.test.ts",
          diff:
            "@@\n-    expect(discounted(5000, 10)).toBe(4500);\n" +
            "+    expect(discounted(5000, 10)).toBeDefined();",
        },
        checks: [
          { name: "test-code-only", passed: true, detail: "one test file changed" },
          { name: "passes-unchanged-code", passed: true, detail: "the suite is green" },
          {
            name: "kills-a-mutant",
            passed: false,
            detail: "killed 0 of 3 injected mutants: the assertion cannot fail",
          },
        ],
        refusalReason: "kills-no-mutant",
        killedMutantIds: [],
      },
      {
        testId: "basket::rejects a negative quantity",
        testName: "rejects a negative quantity",
        suitePath: "apps/web/src/__tests__/basket.criteria.test.ts",
        failureMessage: "expected a RangeError, got none",
        passedOnUnchangedRunId: "",
        classification: "regression",
        classifiedBy: "trace-unchanged",
        evidence: {
          tracedTo: ["R-9"],
          changedArtefacts: [],
          citedDiffSpan: "",
          refereeReasoning: "",
        },
        accepted: false,
        attempts: 0,
        rejectedDrafts: [],
        diff: null,
        checks: [],
        refusalReason: null,
        killedMutantIds: [],
      },
    ],
  };
  const attempts = report.attempts;
  const healed = attempts.filter((one) => one.accepted).length;
  const refused = attempts.filter((one) => !one.accepted && one.refusalReason).length;
  const brittle = attempts.filter((one) => one.classification === "brittle").length;
  return {
    ...report,
    healed,
    refused,
    flaggedRegressions: attempts.filter((one) => one.classification === "regression").length,
    // The gap between these two is the guard's effect, which is the number the
    // study exists to report. Naive counts every repair that was produced;
    // strict counts only the ones the guard accepted.
    naiveConvergence: brittle ? Math.round(((healed + refused) / brittle) * 1000) / 10 : 0,
    strictConvergence: brittle ? Math.round((healed / brittle) * 1000) / 10 : 0,
  } as unknown as HealReport;
}

const HIGH_BANDS = ["critical", "high"];

/**
 * What each weakness class scores, from the component's severity table.
 *
 * Stated rather than computed. The CVSS arithmetic lives in the contracts
 * package and is checked there against published vectors; a second
 * implementation in TypeScript, for fixtures, would be a second thing to keep
 * correct and the first thing to drift. `coherence.test.ts` holds these to the
 * published values, so a wrong number here fails a test rather than teaching
 * the UI to render a severity the server would never send.
 */
const SCORES: Record<string, { baseScore: number; severity: string }> = {
  "CWE-89": { baseScore: 9.8, severity: "critical" },
  "CWE-798": { baseScore: 9.1, severity: "critical" },
  "CWE-327": { baseScore: 5.9, severity: "medium" },
};

function validationReport(version: number): ValidationReport {
  const factors = (
    confidentiality: string,
    integrity: string,
    availability: string,
    complexity = "L",
  ) => ({
    attackVector: "N",
    attackComplexity: complexity,
    privilegesRequired: "N",
    userInteraction: "N",
    scope: "U",
    confidentiality,
    integrity,
    availability,
  });

  const report = {
    reportVersion: "1.0.0",
    version,
    generatedAt: AT,
    target: "apps/api",
    findings: [
      {
        id: "CWE-89:orders:36",
        cwe: "CWE-89",
        title: "sql injection",
        origin: "merged",
        raisedBy: ["scanner", "trained"],
        evidence: {
          path: "apps/api/src/routes/orders.ts",
          startLine: 36,
          endLine: 36,
          snippet: '  const rows = await db.query("select * from orders where id = " + id);',
        },
        factors: factors("H", "H", "H"),
        status: "open",
        explanation: "The path parameter reaches the query unescaped.",
        remediation: "Use a parameterised query.",
        confidence: 0.8,
        confidenceSource: "arm-agreement",
        severityReasoning:
          "SQL injection reaches the database with the application's own rights, so all three impacts are high",
        runId: "run-1",
      },
      {
        id: "CWE-798:config:12",
        cwe: "CWE-798",
        title: "hardcoded credential",
        origin: "trained",
        raisedBy: ["trained"],
        evidence: {
          path: "apps/api/src/config.ts",
          startLine: 12,
          endLine: 12,
          snippet: '  const REPORTING_TOKEN = "s3cr3t-reporting-token";',
        },
        factors: factors("H", "H", "N"),
        status: "open",
        explanation: "",
        remediation: "",
        confidence: 0.5,
        confidenceSource: "scanner-rule",
        severityReasoning:
          "a credential in the source is a credential in every clone and every build cache",
        runId: "run-1",
      },
      {
        id: "CWE-327:hash:49",
        cwe: "CWE-327",
        title: "weak hashing algorithm",
        origin: "scanner",
        raisedBy: ["scanner"],
        evidence: {
          path: "apps/api/src/auth/hash.ts",
          startLine: 49,
          endLine: 49,
          snippet: '  return createHash("md5").update(password).digest("hex");',
        },
        factors: factors("H", "N", "N", "H"),
        status: "dismissed",
        explanation: "",
        remediation: "",
        confidence: 0.5,
        confidenceSource: "scanner-rule",
        severityReasoning: "a broken algorithm exposes what it was protecting",
        runId: "run-1",
      },
    ],
    refusedEvidence: [
      {
        origin: "llm",
        cwe: "CWE-22",
        reason: "snippet-does-not-match",
        claimedPath: "apps/api/src/routes/reports.ts",
        claimedStartLine: 58,
        detail: "quoted code that is not in the file",
      },
    ],
    detectorRuns: [
      {
        arm: "scanner",
        modelId: "semgrep 1.176.1 + findsecbugs 4.10.4",
        startedAt: AT,
        durationSeconds: 29.6,
        promptTokens: 0,
        completionTokens: 0,
        costUsd: 0,
        offline: false,
        filesScanned: 9,
      },
      {
        arm: "trained",
        modelId: "microsoft/graphcodebert-base fine tuned, c3-juliet",
        startedAt: AT,
        durationSeconds: 161.5,
        promptTokens: 0,
        completionTokens: 0,
        costUsd: 0,
        offline: true,
        filesScanned: 9,
      },
    ],
    tests: {
      run: 18,
      passed: 17,
      failed: 1,
      skipped: 0,
      lineCoverage: 86.4,
      mutationScore: 61.4,
    },
    approvedBy: null,
    approvedAt: null,
  };
  const open = report.findings.filter((one) => one.status === "open");
  return {
    ...report,
    findings: report.findings.map((finding) => ({ ...finding, ...SCORES[finding.cwe] })),
    openFindings: open.length,
    openCriticalOrHigh: open.filter((one) => HIGH_BANDS.includes(SCORES[one.cwe]?.severity ?? ""))
      .length,
    refusedCount: report.refusedEvidence.length,
  } as unknown as ValidationReport;
}

function remediation(version: number): RemediationProposals {
  const report = {
    version,
    generatedAt: AT,
    target: "apps/api",
    proposals: [
      {
        id: "fix-CWE-89:orders:36",
        findingId: "CWE-89:orders:36",
        cwe: "CWE-89",
        generatedAt: AT,
        summary: "use a parameterised query",
        patch: [
          {
            path: "apps/api/src/routes/orders.ts",
            diff:
              '@@\n-  const rows = await db.query("select * from orders where id = " + id);\n' +
              '+  const rows = await db.query("select * from orders where id = $1", [id]);',
          },
        ],
        risk: {
          level: "low",
          statement:
            "Low risk: the patch changes 2 lines in 1 file, 3 tests cover the lines it changes, and no endpoint contract moves.",
          facts: [
            { label: "files changed", value: 1 },
            { label: "lines changed", value: 2 },
            { label: "tests covering those lines", value: 3 },
            { label: "endpoints whose contract moves", value: 0 },
          ],
        },
        affectedEndpoints: [],
        affectedTests: ["lists the orders", "reads one order"],
        state: "proposed",
        decidedBy: "",
        decidedAt: null,
        decisionNote: "",
        appliedCodeVersion: null,
        reverification: null,
      },
    ],
  };
  return {
    ...report,
    proposals: report.proposals.map((one) => ({
      ...one,
      awaitingDecision: one.state === "proposed",
    })),
    awaitingDecision: report.proposals.filter((one) => one.state === "proposed").length,
  } as unknown as RemediationProposals;
}

export function buildTestSnapshot(
  projectId: string,
  posture: TestPosture,
  codeVersion: number,
): TestSnapshot {
  const version = posture === "not-started" ? 0 : 1;
  const hasArtefacts = posture === "awaiting" || posture === "approved";
  const approved = posture === "approved";

  return {
    projectId,
    testVersion: version,
    codeVersion,
    testedCodeVersion: version ? codeVersion : 0,
    stages: stages(posture, version),
    tests: hasArtefacts ? testReport(version) : null,
    heal: hasArtefacts ? healReport(version) : null,
    validation: hasArtefacts ? validationReport(version) : null,
    remediation: hasArtefacts ? remediation(version) : null,
    run: null,
    gate: {
      decision: approved
        ? {
            kind: "approved",
            at: AT,
            by: "you",
            version,
            note: "Two findings open and accepted for this release.",
          }
        : null,
      history: [],
    },
    thread: hasArtefacts
      ? [
          {
            id: "t-1",
            kind: "stage_summary",
            stageId: "self-healing",
            author: "system",
            content:
              "1 repair accepted, 1 refused for weakening its assertion, 1 regression flagged.",
            at: AT,
            producedVersion: null,
          },
        ]
      : [],
    codeMovedOn: false,
    openFindings: hasArtefacts ? 2 : 0,
    refusedRepairs: hasArtefacts ? 1 : 0,
    awaitingDecision: hasArtefacts ? 1 : 0,
  } as unknown as TestSnapshot;
}

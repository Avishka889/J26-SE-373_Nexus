import { describe, expect, it } from "vitest";
import { TEST_STAGE_IDS } from "@/types/project";
import { buildTestSnapshot, type TestPosture } from "./buildTestSnapshot";
import { testPostureFor } from "./testingDb";

/**
 * The fixture has to be a thing the server could have sent.
 *
 * `buildTestSnapshot` casts through `unknown` at its boundary, because the
 * generated types carry computed fields and narrow unions that a literal
 * widens. That cast buys convenience and gives up the checking, so the
 * checking comes back here at runtime, where it can catch the thing a type
 * cannot anyway: a stated count that disagrees with the array it counts.
 *
 * The failure this prevents is specific and has happened in this repository
 * before. A fixture says seventeen tests passed over a list holding nine; the
 * UI renders seventeen quite happily; nobody notices until the flag flips and
 * the server sends nine.
 */

const POSTURES: TestPosture[] = ["not-started", "running", "awaiting", "approved"];

describe("the testing fixture is shaped like the contract", () => {
  it.each(POSTURES)("%s has every stage the client indexes", (posture) => {
    const snapshot = buildTestSnapshot("p1", posture, 1);

    expect(Object.keys(snapshot.stages).sort()).toEqual([...TEST_STAGE_IDS].sort());
  });

  it.each(POSTURES)("%s never claims a version it has no artefact for", (posture) => {
    const snapshot = buildTestSnapshot("p1", posture, 1);

    if (snapshot.testVersion === 0) {
      expect(snapshot.tests).toBeNull();
      expect(snapshot.validation).toBeNull();
      expect(snapshot.heal).toBeNull();
    }
  });

  it("a stage that failed says why, and one that did not carries no error", () => {
    for (const posture of POSTURES) {
      for (const stage of Object.values(buildTestSnapshot("p1", posture, 1).stages)) {
        if (stage.status === "failed") expect(stage.error).toBeTruthy();
        else expect(stage.error).toBeFalsy();
      }
    }
  });
});

describe("every derived count matches what it counts", () => {
  const snapshot = buildTestSnapshot("p1", "awaiting", 1);

  it("the test report's totals come from its cases", () => {
    const cases = snapshot.tests!.suites.flatMap((suite) => suite.cases);
    const by = (outcome: string) => cases.filter((one) => one.outcome === outcome).length;

    expect(snapshot.tests!.total).toBe(cases.length);
    expect(snapshot.tests!.passed).toBe(by("passed"));
    expect(snapshot.tests!.failed).toBe(by("failed"));
  });

  it("the mutation score is killed over the total", () => {
    const mutation = snapshot.tests!.mutation!;
    const total = Number(mutation.killed) + Number(mutation.survived) + Number(mutation.inconclusive);

    expect(mutation.total).toBe(total);
    expect(mutation.score).toBeCloseTo((Number(mutation.killed) / total) * 100, 1);
  });

  it("the heal report's counts come from its attempts", () => {
    const attempts = snapshot.heal!.attempts;

    expect(snapshot.heal!.healed).toBe(attempts.filter((one) => one.accepted).length);
    expect(snapshot.heal!.flaggedRegressions).toBe(
      attempts.filter((one) => one.classification === "regression").length,
    );
  });

  it("strict convergence is never above naive, which is the guard's whole effect", () => {
    expect(snapshot.heal!.strictConvergence).toBeLessThanOrEqual(snapshot.heal!.naiveConvergence);
  });

  it("open findings are the ones nobody dismissed", () => {
    const open = snapshot.validation!.findings.filter((one) => one.status === "open");

    expect(snapshot.validation!.openFindings).toBe(open.length);
    expect(snapshot.openFindings).toBe(open.length);
  });

  it("the refused count matches the refusals", () => {
    expect(snapshot.validation!.refusedCount).toBe(snapshot.validation!.refusedEvidence.length);
  });

  it("proposals awaiting a decision are the ones still proposed", () => {
    const waiting = snapshot.remediation!.proposals.filter((one) => one.state === "proposed");

    expect(snapshot.remediation!.awaitingDecision).toBe(waiting.length);
    expect(snapshot.awaitingDecision).toBe(waiting.length);
  });
});

describe("severities are the published ones", () => {
  /**
   * The CVSS arithmetic lives in the contracts package and is checked there
   * against published vectors. These are the values that arithmetic produces,
   * restated for the fixture, so a wrong one fails here rather than teaching
   * the UI to render a severity the server would never send.
   */
  it.each([
    ["CWE-89", 9.8, "critical"],
    ["CWE-798", 9.1, "critical"],
    ["CWE-327", 5.9, "medium"],
  ])("%s scores %s", (cwe, score, band) => {
    const finding = buildTestSnapshot("p1", "awaiting", 1).validation!.findings.find(
      (one) => one.cwe === cwe,
    );

    expect(finding?.baseScore).toBe(score);
    expect(finding?.severity).toBe(band);
  });
});

describe("the posture follows the project's own status", () => {
  it("nothing has been tested before the code gate", () => {
    for (const status of ["draft", "analyzing", "design", "code"] as const) {
      expect(testPostureFor(status)).toBe("not-started");
    }
  });

  it("a project in testing is waiting on a decision", () => {
    expect(testPostureFor("testing")).toBe("awaiting");
  });

  it("anything downstream of the gate has been approved", () => {
    for (const status of ["deploy", "complete"] as const) {
      expect(testPostureFor(status)).toBe("approved");
    }
  });
});

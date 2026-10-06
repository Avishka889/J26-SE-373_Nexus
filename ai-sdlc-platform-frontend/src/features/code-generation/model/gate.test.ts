import { describe, expect, it } from "vitest";
import { CODE_STAGE_IDS } from "@/types/project";
import { codeConcerns } from "./gate";
import type { CodeSnapshot } from "../api/types";

function snapshot({
  failed = [],
  steps,
  agreementErrors = 0,
  contract = null,
}: {
  failed?: string[];
  steps?: { name: string; outcome: string }[];
  agreementErrors?: number;
  contract?: unknown;
}): CodeSnapshot {
  const stages = Object.fromEntries(
    CODE_STAGE_IDS.map((id) => [id, { id, status: failed.includes(id) ? "failed" : "complete" }]),
  );
  return {
    stages,
    repository: steps ? { build: { steps } } : null,
    agreement: {
      findings: Array.from({ length: agreementErrors }, () => ({ severity: "error" })),
    },
    contract,
  } as unknown as CodeSnapshot;
}

/**
 * A code version was approved with its typecheck failing, in one click, and the
 * line that said so was cut off on a phone. What failed is now said first, and
 * approving over it needs a note.
 */
describe("what a code approval has to answer for", () => {
  it("says which build step did not pass, and how", () => {
    expect(
      codeConcerns(snapshot({ steps: [{ name: "install", outcome: "passed" }, { name: "typecheck", outcome: "failed" }] })),
    ).toEqual(["the build did not pass: typecheck failed"]);
    expect(codeConcerns(snapshot({ steps: [{ name: "test", outcome: "timed-out" }] }))).toEqual([
      "the build did not pass: test timed out",
    ]);
  });

  it("counts a build that never ran, and agreement errors", () => {
    expect(codeConcerns(snapshot({ agreementErrors: 2 }))).toEqual([
      "the build did not run",
      "2 agreement errors between the code and the contract",
    ]);
  });

  it("is nothing for a version that built and agrees", () => {
    expect(codeConcerns(snapshot({ steps: [{ name: "build", outcome: "passed" }] }))).toEqual([]);
  });
});

const BOOK_APPOINTMENT = {
  ruleId: "screen-action-has-an-endpoint",
  severity: "error",
  reason: "screen flow-a1/s2 ('Book Appointment') is a form with 5 fields and no write endpoint traces to it",
  subject: "flow-a1/s2",
};

function contract(chosen: string, ruleErrors: number, llmErrors: number | null) {
  return {
    chosen,
    llmArm: llmErrors === null ? null : { endpoints: [] },
    comparison: {
      rule: { endpoints: 6, errors: ruleErrors },
      llm: { endpoints: 13, errors: llmErrors ?? 0 },
    },
    ruleFindings: Array.from({ length: ruleErrors }, () => BOOK_APPOINTMENT),
  };
}

/**
 * The clinic project was approved over a contract with no way to create a
 * doctor or a patient. The rule arm's own check had said so, and the review
 * asked nothing about it; the model's contract, with thirteen endpoints, had
 * no error.
 */
describe("an error in the API contract the code was built from", () => {
  const BUILT = { steps: [{ name: "build", outcome: "passed" }] };

  it("is outstanding, with the first reason, and names the other contract when it has none", () => {
    expect(codeConcerns(snapshot({ ...BUILT, contract: contract("rule", 1, 0) }))).toEqual([
      "1 error in the API contract it was built from (screen flow-a1/s2 ('Book Appointment') is a form with 5 fields and no write endpoint traces to it); the AI model's contract has none",
    ]);
  });

  it("counts the model arm's errors when that is the one chosen", () => {
    expect(codeConcerns(snapshot({ ...BUILT, contract: contract("llm", 0, 3) }))).toEqual([
      "3 errors in the API contract it was built from; the rule-based contract has none",
    ]);
  });

  it("says nothing of a model arm that failed", () => {
    expect(codeConcerns(snapshot({ ...BUILT, contract: contract("rule", 2, null) }))).toEqual([
      "2 errors in the API contract it was built from (screen flow-a1/s2 ('Book Appointment') is a form with 5 fields and no write endpoint traces to it)",
    ]);
  });

  it("asks nothing of a warning, which a review weighs but need not answer for", () => {
    const warned = { ...contract("rule", 0, 0), ruleFindings: [{ ...BOOK_APPOINTMENT, severity: "warning" }] };

    expect(codeConcerns(snapshot({ ...BUILT, contract: warned }))).toEqual([]);
  });

  it("asks nothing of a contract without errors, or of a merged one", () => {
    expect(codeConcerns(snapshot({ ...BUILT, contract: contract("rule", 0, 4) }))).toEqual([]);
    expect(codeConcerns(snapshot({ ...BUILT, contract: contract("merged", 2, 2) }))).toEqual([]);
  });
});


import { describe, expect, it } from "vitest";
import { CODE_STAGE_IDS } from "@/types/project";
import { codeConcerns } from "./gate";
import type { CodeSnapshot } from "../api/types";

function snapshot({
  failed = [],
  steps,
  agreementErrors = 0,
}: {
  failed?: string[];
  steps?: { name: string; outcome: string }[];
  agreementErrors?: number;
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

import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, render, screen } from "@testing-library/react";
import { CODE_STAGE_IDS } from "@/types/project";
import type { ApiContract, CodeSnapshot, CodeStages } from "../../api/types";
import { StageApiContract } from "./StageApiContract";

afterEach(cleanup);

const CONTRACT: ApiContract = { version: 1, entities: [], endpoints: [] };

function snapshot(): CodeSnapshot {
  const stages = Object.fromEntries(
    CODE_STAGE_IDS.map((id) => [
      id,
      { id, status: "pending" as const, generatedFromVersion: 0, generatedAt: null, summary: null, error: null },
    ]),
  ) as CodeStages;
  return {
    projectId: "p1",
    codeVersion: 1,
    designVersion: 1,
    designBlocker: null,
    generatedFromDesignVersion: 1,
    stages,
    run: null,
    gate: { decision: null, history: [] },
    approvedThrough: null,
    scope: null,
    nextSprint: null,
    techStack: null,
    contract: {
      version: 1,
      chosen: "rule",
      comparison: null,
      contract: CONTRACT,
      llmArm: null,
      llmFailure: "the model's draft broke the rule catalogue twice",
      ruleArm: CONTRACT,
      ruleFindings: [
        {
          ruleId: "screen-action-has-an-endpoint",
          severity: "error",
          reason: "screen shop/checkout is a form with 2 fields and no write endpoint traces to it",
          subject: "shop/checkout",
        },
      ],
    },
    agreement: null,
    repository: null,
    diff: null,
    thread: [],
  };
}

describe("the rule-based arm", () => {
  // Its own findings lived only in the comparison, which a failed model arm
  // leaves out, so it read as having no violations (review item C2-3).
  it("keeps its own findings when the model arm failed", () => {
    render(
      <StageApiContract
        snapshot={snapshot()}
        onChooseArm={vi.fn()}
        onJumpToScreen={vi.fn()}
        onOpenRequirement={vi.fn()}
        onDownloadOpenApi={vi.fn(async () => undefined)}
        busy={false}
      />,
    );

    expect(screen.getByText(/1 rule violation\b/)).toBeTruthy();
    expect(
      screen.getByText("screen shop/checkout is a form with 2 fields and no write endpoint traces to it"),
    ).toBeTruthy();
  });
});

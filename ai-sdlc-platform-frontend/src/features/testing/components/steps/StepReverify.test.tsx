import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, render, screen } from "@testing-library/react";
import { buildTestSnapshot } from "../../fixtures/buildTestSnapshot";
import type { AppliedFix, Finding } from "../../fixtures/types";
import { buildView } from "../../model/view";
import { StepReverify } from "./StepReverify";

afterEach(cleanup);

const FINDING: Finding = {
  id: "CWE-89:accounts:6",
  cwe: "CWE-89",
  name: "SQL injection",
  severity: "high",
  cvss: 8.1,
  file: "apps/api/src/routes/accounts.ts",
  line: 6,
  status: "fix-applied",
  foundBy: ["local"],
  explanation: "The name reaches the query unparameterised.",
};

describe("the re-verify step", () => {
  // A comparison recorded before it looked for the finding is asked again, and
  // the note says why, not that the tests still have to run (review item C3-7).
  it("says why a fix is asked to re-verify again", () => {
    const note =
      "Re-verifying compares the same two runs again, and looks for the finding itself in the scan after the fix.";
    const fix: AppliedFix = {
      findingId: FINDING.id,
      appliedBy: "you",
      appliedAt: "2026-10-09T10:00:00Z",
      scan: { state: "pending", detail: "Counted totals only" },
      suite: { state: "pass", detail: "no test broke" },
      verdict: "This comparison counted totals only and did not look for the finding itself: re-verify to check it.",
      pendingNote: note,
    };
    const view = {
      ...buildView({ data: buildTestSnapshot("p1", "awaiting", 1), reviewer: "you" }),
      findings: [FINDING],
      fixes: [fix],
    };

    render(<StepReverify view={view} onGoTo={vi.fn()} onRetry={vi.fn()} onReverify={vi.fn()} />);

    expect(screen.getByRole("button", { name: "Re-verify now" })).toBeTruthy();
    expect(screen.getByText(note)).toBeTruthy();
  });
});

/**
 * With no finding, there is nothing to fix. The stage said "No fix has been
 * applied yet" and offered the findings table, as if one were owed.
 */
describe("remediation after a scan with no findings", () => {
  const base = buildView({ data: buildTestSnapshot("p1", "awaiting", 1), reviewer: "you" });

  it("says there is nothing to remediate, and offers nothing to do", () => {
    render(
      <StepReverify view={{ ...base, findings: [], fixes: [] }} onGoTo={vi.fn()} onRetry={vi.fn()} onReverify={vi.fn()} />,
    );

    expect(screen.getByText("Nothing to remediate")).toBeTruthy();
    expect(screen.getByText(/The scan raised no findings at test version 1/)).toBeTruthy();
    expect(screen.queryByRole("button", { name: /go to the findings/i })).toBeNull();
  });

  it("still offers the findings while there is one and no fix has been applied", () => {
    render(
      <StepReverify
        view={{ ...base, findings: [FINDING], fixes: [] }}
        onGoTo={vi.fn()}
        onRetry={vi.fn()}
        onReverify={vi.fn()}
      />,
    );

    expect(screen.getByText("No fix has been applied yet")).toBeTruthy();
    expect(screen.getByRole("button", { name: /go to the findings/i })).toBeTruthy();
  });
});

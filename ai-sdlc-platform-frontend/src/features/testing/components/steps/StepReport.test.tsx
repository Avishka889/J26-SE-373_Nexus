import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, render, screen } from "@testing-library/react";
import { buildTestSnapshot } from "../../fixtures/buildTestSnapshot";
import { buildView } from "../../model/view";
import { StepReport } from "./StepReport";

afterEach(cleanup);

function review() {
  const onOpenActivity = vi.fn();
  render(
    <StepReport
      view={buildView({ data: buildTestSnapshot("p1", "awaiting", 1), reviewer: "you" })}
      run={null}
      decisionChain={[]}
      onGoTo={vi.fn()}
      onOpenDeployment={vi.fn()}
      onOpenActivity={onOpenActivity}
      onRollback={vi.fn()}
    />,
  );
  return { onOpenActivity };
}

/**
 * The test review carried a copy of the audit log as a table. No other
 * phase's review has one, the Activity Log tab is the same entries, and here
 * it was a scrolling box inside the scrolling page.
 */
describe("the test review and the audit log", () => {
  it("links to the Activity Log for this phase's entries", () => {
    const { onOpenActivity } = review();

    screen.getByRole("button", { name: /Open the Activity Log/ }).click();

    expect(onOpenActivity).toHaveBeenCalledOnce();
  });

  it("does not carry a copy of the log", () => {
    review();

    expect(screen.queryByRole("table")).toBeNull();
    expect(screen.queryByRole("button", { name: /export csv/i })).toBeNull();
  });
});

/**
 * Design Review ends with "Continue to Code Generation" and Code Review with
 * "Continue to Testing & Security", each a button in the panel that records the
 * approval. This review ended with an underlined "Open Deployment" link.
 */
describe("an approved test review", () => {
  it("continues to Deployment with a button, as the other two reviews continue", () => {
    const onOpenDeployment = vi.fn();
    render(
      <StepReport
        view={buildView({ data: buildTestSnapshot("p1", "approved", 1), reviewer: "you" })}
        run={null}
        decisionChain={[]}
        onGoTo={vi.fn()}
        onOpenDeployment={onOpenDeployment}
        onOpenActivity={vi.fn()}
        onRollback={vi.fn()}
      />,
    );

    expect(screen.getByText("Tests approved for test version 1")).toBeTruthy();
    screen.getByRole("button", { name: "Continue to Deployment" }).click();
    expect(onOpenDeployment).toHaveBeenCalledOnce();
  });
});

import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { requirementsApi } from "../../api";
import type { ConsistencyFinding } from "../../api/types";
import { StageSprintPlan } from "./StageSprintPlan";

afterEach(cleanup);

const BEHIND: ConsistencyFinding = {
  ruleId: "story-priority-is-current",
  severity: "warning",
  reason:
    "US-1 was planned as a should-have, and the requirements it realises (R-1) now make it a must-have. Plan the sprint again to rank it there: As a customer, I can pay",
  traces: ["R-1"],
  stageId: "sprint-plan",
};

/**
 * A corrected priority changed the requirement and nothing planned from it: the
 * plan on the page was ranked on the old one, and said nothing (review item C1-2).
 */
describe("a plan ranked before a priority was corrected", () => {
  async function show(behind: ConsistencyFinding[]) {
    const design = await requirementsApi.getDesign("p1");
    const onPlanAgain = vi.fn();
    render(
      <StageSprintPlan
        sprint={design.sprint}
        version={design.requirementsVersion}
        behind={behind}
        onPlanAgain={onPlanAgain}
        onJump={vi.fn()}
      />,
    );
    return onPlanAgain;
  }

  it("says so, names the stories, and plans again on request", async () => {
    const onPlanAgain = await show([BEHIND]);

    expect(screen.getByText("This plan was ranked before a priority was corrected")).toBeTruthy();
    expect(screen.getByText(BEHIND.reason)).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Plan the sprint again" }));

    expect(onPlanAgain).toHaveBeenCalledOnce();
  });

  it("says nothing when the plan is ranked on the priorities held now", async () => {
    await show([]);

    expect(screen.queryByText("This plan was ranked before a priority was corrected")).toBeNull();
    expect(screen.queryByRole("button", { name: "Plan the sprint again" })).toBeNull();
  });
});

/**
 * The sprint is divided by priority and size, so it could take on a story the
 * design connects to something only a backlog story builds (review item C1-5).
 */
describe("a sprint story that needs a backlog story", () => {
  async function show(flagged: boolean) {
    const design = await requirementsApi.getDesign("p1");
    const sprint = design.sprint!;
    const [story] = sprint.proposed;
    const [needed] = sprint.backlog;
    render(
      <StageSprintPlan
        sprint={{
          ...sprint,
          backlogDependencies: flagged
            ? [
                {
                  storyId: story.id,
                  needs: needed.id,
                  because: "Payment Service calls Ledger, and nothing in this sprint builds Ledger",
                },
              ]
            : [],
        }}
        version={design.requirementsVersion}
        behind={[]}
        onPlanAgain={vi.fn()}
        onJump={vi.fn()}
      />,
    );
    return { story, needed };
  }

  it("is marked on the story, with the story it needs and why", async () => {
    const { needed } = await show(true);

    expect(screen.getByText(`Needs ${needed.id}`)).toBeTruthy();
    expect(
      screen.getByText(
        `Needs ${needed.id}, which is in the backlog: Payment Service calls Ledger, and nothing in this sprint builds Ledger.`,
        { exact: false },
      ),
    ).toBeTruthy();
  });

  it("is not marked when the sprint needs nothing from the backlog", async () => {
    await show(false);

    expect(screen.queryByText(/^Needs US-/)).toBeNull();
  });
});

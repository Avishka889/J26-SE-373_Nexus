import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { codeApi } from "../../api";
import type { CodeSnapshot, NextSprint } from "../../api/types";
import { StageSprintScope } from "./StageSprintScope";

afterEach(cleanup);

const SPRINT_2: NextSprint = {
  number: 2,
  stories: [
    { id: "US-4", title: "Export a report", points: 8, priority: "should" },
    { id: "US-5", title: "Share a report", points: 5, priority: "could" },
  ],
  points: 13,
  velocity: 20,
  velocityBasis: "assumed, not measured",
};

async function scopeWith(nextSprint: NextSprint | null): Promise<CodeSnapshot> {
  const snapshot = await codeApi.getCode("p1");
  return { ...snapshot, nextSprint };
}

function renderScope(
  snapshot: CodeSnapshot,
  onPlanNextSprint = vi.fn(),
  busy = false,
  reviewOpen = false,
) {
  render(
    <StageSprintScope
      snapshot={snapshot}
      onToggle={vi.fn()}
      onPlanNextSprint={onPlanNextSprint}
      onOpenScreens={vi.fn()}
      onOpenRequirement={vi.fn()}
      busy={busy}
      reviewOpen={reviewOpen}
    />,
  );
  return onPlanNextSprint;
}

/**
 * The build grows a sprint at a time: a story in it names its sprint, and the
 * next sprint is shown, with what it would take, before anyone plans it.
 */
describe("the next sprint on the scope stage", () => {
  it("names the sprint each story in the build was planned in", async () => {
    const snapshot = await scopeWith(null);
    const inScope = snapshot.scope!.stories.filter(
      (story) => story.inScope,
    ).length;

    renderScope(snapshot);

    expect(screen.getAllByText("Sprint 1")).toHaveLength(inScope);
  });

  it("shows the stories the next sprint would take, and plans it on asking", async () => {
    const onPlan = renderScope(await scopeWith(SPRINT_2));

    expect(screen.getByText("Export a report")).toBeTruthy();
    expect(screen.getByText("Share a report")).toBeTruthy();
    expect(
      screen.getByText(/13 of a 20 point velocity assumption/),
    ).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Plan sprint 2" }));
    expect(onPlan).toHaveBeenCalledTimes(1);
  });

  it("does not plan while the code is generating", async () => {
    renderScope(await scopeWith(SPRINT_2), vi.fn(), true);

    expect(
      (
        screen.getByRole("button", {
          name: "Plan sprint 2",
        }) as HTMLButtonElement
      ).disabled,
    ).toBe(true);
  });

  // C2-10: planning the next sprint while this build's review was open decided
  // the review as requested changes. The next sprint goes on top of a build
  // that has been reviewed, so the page waits for the decision and says so.
  it("waits for the code review to be decided, and says so", async () => {
    const onPlan = renderScope(await scopeWith(SPRINT_2), vi.fn(), false, true);

    const plan = screen.getByRole("button", {
      name: "Plan sprint 2",
    }) as HTMLButtonElement;
    expect(plan.disabled).toBe(true);
    expect(screen.getByText(/Decide the code review first/)).toBeTruthy();
    fireEvent.click(plan);
    expect(onPlan).not.toHaveBeenCalled();
  });

  it("says so when every story is in the build", async () => {
    renderScope(await scopeWith({ ...SPRINT_2, stories: [], points: 0 }));

    expect(
      screen.getByText(/Every story in the sprint plan is in this build/),
    ).toBeTruthy();
    expect(screen.queryByRole("button", { name: /Plan sprint/ })).toBeNull();
  });
});

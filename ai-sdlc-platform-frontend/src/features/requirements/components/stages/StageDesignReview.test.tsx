import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { requirementsApi } from "../../api";
import { projectDomain } from "../../model/domain";
import type { DesignSnapshot } from "../../api/types";
import { StageDesignReview } from "./StageDesignReview";

afterEach(cleanup);

// The demo's NexusPay design, at its review, through the api as a page reads it.
const base = await requirementsApi.getDesign("p1");

function review(answers: Record<string, string>, onApplyAnswers = vi.fn()) {
  const snapshot: DesignSnapshot = {
    ...base,
    // Only the answers this test gives: the demo's questions come answered.
    questions: base.questions.map((q) => ({ ...q, answer: answers[q.id] ?? null })),
  };
  render(
    <MemoryRouter>
      <StageDesignReview
        snapshot={snapshot}
        domain={projectDomain(snapshot.graph)}
        onGoToStage={vi.fn()}
        onJump={vi.fn()}
        onContinue={vi.fn()}
        onOpenChat={vi.fn()}
        onApplyAnswers={onApplyAnswers}
      />
    </MemoryRouter>,
  );
  return { snapshot, onApplyAnswers };
}

/**
 * Answering the last question regenerated the whole design, a model run, with
 * no word beforehand, while the page said to answer before deciding. Applying
 * the answers is now the reader's own act, said for what it does.
 */
describe("the answers at the design review", () => {
  it("are applied only when the reader asks, and the page says what that does", () => {
    const first = base.questions[0];
    const { onApplyAnswers } = review({ [first.id]: "Only the finance team." });

    expect(screen.getByText("1 answer not applied yet")).toBeTruthy();
    expect(screen.getByText(/runs the model again/)).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Apply the answers" }));

    expect(onApplyAnswers).toHaveBeenCalledOnce();
  });

  it("offers nothing to apply before any answer", () => {
    review({});

    expect(screen.queryByRole("button", { name: "Apply the answers" })).toBeNull();
  });
});

describe("the screens the review counts as missing", () => {
  // The review counted every story without a screen, while Wireframes counts only
  // the stories a person performs: work no actor owns could never have a screen,
  // and counting it reported a gap that was not there (review item C1-11).
  it("counts only the stories that need a screen", () => {
    const row = { screenIds: [] as string[], storyTitle: "A story" };
    const snapshot: DesignSnapshot = {
      ...base,
      wireframes: {
        ...base.wireframes,
        coverage: [
          { ...row, storyId: "US-1", covered: true, needsScreen: true, screenIds: ["s-1"] },
          { ...row, storyId: "US-2", covered: false, needsScreen: true },
          { ...row, storyId: "US-3", covered: false, needsScreen: false },
        ],
      },
    };
    render(
      <MemoryRouter>
        <StageDesignReview
          snapshot={snapshot}
          domain={projectDomain(snapshot.graph)}
          onGoToStage={vi.fn()}
          onJump={vi.fn()}
          onContinue={vi.fn()}
          onOpenChat={vi.fn()}
          onApplyAnswers={vi.fn()}
        />
      </MemoryRouter>,
    );

    const tile = screen.getByText("Screens missing").parentElement;
    expect(tile?.querySelector(".tp-num")?.textContent).toBe("1");
  });
});

describe("what a design version changed", () => {
  // A change note regenerates the design, and the review showed the new version
  // with nothing saying what had moved (review item C1-6).
  const show = (changes: DesignSnapshot["changes"]) => {
    const snapshot: DesignSnapshot = { ...base, requirementsVersion: 2, changes };
    render(
      <MemoryRouter>
        <StageDesignReview
          snapshot={snapshot}
          domain={projectDomain(snapshot.graph)}
          onGoToStage={vi.fn()}
          onJump={vi.fn()}
          onContinue={vi.fn()}
          onOpenChat={vi.fn()}
          onApplyAnswers={vi.fn()}
        />
      </MemoryRouter>,
    );
  };

  it("names the requirements and stories added, removed and changed", () => {
    show({
      fromVersion: 1,
      requirements: {
        fromVersion: 1,
        toVersion: 2,
        added: ["R-7"],
        removed: ["R-3"],
        changed: [{ requirementId: "R-2", field: "text", before: "old words", after: "new words" }],
      },
      stories: { added: ["US-5"], removed: [], changed: ["US-1", "US-2"] },
    });

    expect(screen.getByText("What changed since version 1")).toBeTruthy();
    expect(screen.getByText("Requirements: 1 added (R-7), 1 removed (R-3), 1 changed (R-2).")).toBeTruthy();
    expect(screen.getByText("Stories: 1 added (US-5), 2 changed (US-1, US-2).")).toBeTruthy();
  });

  it("says so when nothing moved", () => {
    show({
      fromVersion: 1,
      requirements: { fromVersion: 1, toVersion: 2, added: [], removed: [], changed: [] },
      stories: { added: [], removed: [], changed: [] },
    });

    expect(screen.getByText("Requirements: none changed.")).toBeTruthy();
    expect(screen.getByText("Stories: none changed.")).toBeTruthy();
  });

  it("says nothing on a first version", () => {
    show(null);

    expect(screen.queryByText(/What changed since version/)).toBeNull();
  });
});


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

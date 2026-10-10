import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { requirementsApi } from "../../api";
import type { DesignSnapshot } from "../../api/types";
import { StageRequirements } from "./StageRequirements";

afterEach(cleanup);

// Every mutation the stage could reach, idle; only clicks would call one.
const mutations = new Proxy(
  {},
  { get: () => ({ isPending: false, mutate: vi.fn(), mutateAsync: vi.fn(async () => undefined) }) },
) as never;

/**
 * The design asks its questions before it builds the rest, and never blocks.
 *
 * A run built every stage on the assumptions it stated, and applying the
 * answers built every stage again. Now a run whose analysis asked questions
 * pauses after Requirements Analysis, and this panel is where the reader goes on:
 * with the answers, or with the assumptions.
 */
describe("the questions the design waits on", () => {
  async function snapshot(over: Partial<DesignSnapshot> = {}): Promise<DesignSnapshot> {
    const base = await requirementsApi.getDesign("p1");
    return {
      ...base,
      questions: base.questions.map((question) => ({ ...question, answer: null, answeredAt: null })),
      queuedChanges: [],
      questionsPending: true,
      ...over,
    };
  }

  function show(design: DesignSnapshot) {
    const onContinueWithAnswers = vi.fn(async () => undefined);
    const onContinueWithAssumptions = vi.fn(async () => undefined);
    const { container } = render(
      <StageRequirements
        snapshot={design}
        mutations={mutations}
        focusedRequirementId={null}
        onClearFocus={vi.fn()}
        onJump={vi.fn()}
        onOpenChat={vi.fn()}
        onContinueWithAnswers={onContinueWithAnswers}
        onContinueWithAssumptions={onContinueWithAssumptions}
      />,
    );
    return { container, onContinueWithAnswers, onContinueWithAssumptions };
  }

  it("come first, and say the rest of the design waits on them", async () => {
    const design = await snapshot();
    expect(design.questions.length).toBeGreaterThan(1);

    const { container } = show(design);

    const text = container.textContent ?? "";
    expect(text).toContain("The rest of the design waits on these questions.");
    expect(text.indexOf("The rest of the design waits")).toBeLessThan(
      text.indexOf("What was read from your input"),
    );
  });

  it("can always go on with the assumptions, and with the answers once there is one", async () => {
    const { onContinueWithAssumptions } = show(await snapshot());

    const answers = screen.getByRole("button", { name: "Continue with my answers" });
    expect((answers as HTMLButtonElement).disabled).toBe(true);
    expect(screen.getByText("Answer a question first to continue with your answers.")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Continue with the assumptions" }));
    expect(onContinueWithAssumptions).toHaveBeenCalledOnce();
  });

  it("goes on with the answers once a question is answered", async () => {
    const design = await snapshot();
    const [first, ...rest] = design.questions;
    const { onContinueWithAnswers } = show({
      ...design,
      questions: [{ ...first, answer: "Hold it.", answeredAt: "2026-10-06T08:00:00Z" }, ...rest],
    });

    fireEvent.click(screen.getByRole("button", { name: "Continue with my answers" }));

    expect(onContinueWithAnswers).toHaveBeenCalledOnce();
  });

  it("counts a note written while it waits as something to go on with", async () => {
    show(await snapshot({ queuedChanges: ["Track due dates too."] }));

    const answers = screen.getByRole("button", { name: "Continue with my answers" });
    expect((answers as HTMLButtonElement).disabled).toBe(false);
  });

  it("is the plain pointer to the conversation when nothing waits on it", async () => {
    show(await snapshot({ questionsPending: false }));

    expect(screen.queryByRole("button", { name: "Continue with my answers" })).toBeNull();
    expect(screen.queryByRole("button", { name: "Continue with the assumptions" })).toBeNull();
    expect(screen.getByRole("button", { name: /answer in chat/i })).toBeTruthy();
  });
});

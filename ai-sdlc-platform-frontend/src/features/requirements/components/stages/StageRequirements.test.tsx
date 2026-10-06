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

/**
 * A requirement's priority came from a rule and nothing could correct it: the
 * wording could be edited, the priority could not (review item C1-2).
 */
describe("a requirement's priority", () => {
  function show(design: DesignSnapshot, setRequirementPriority = vi.fn(async () => undefined)) {
    const idle = { isPending: false, mutate: vi.fn(), mutateAsync: vi.fn(async () => undefined) };
    const these = new Proxy(
      {},
      {
        get: (_target, name) =>
          name === "setRequirementPriority" ? { ...idle, mutateAsync: setRequirementPriority } : idle,
      },
    ) as never;
    render(
      <StageRequirements
        snapshot={design}
        mutations={these}
        focusedRequirementId={design.requirements[0].id}
        onClearFocus={vi.fn()}
        onJump={vi.fn()}
        onOpenChat={vi.fn()}
        onContinueWithAnswers={vi.fn(async () => undefined)}
        onContinueWithAssumptions={vi.fn(async () => undefined)}
      />,
    );
    return setRequirementPriority;
  }

  async function design(over: { priority: "must" | "should" | "could"; priorityCorrected: boolean }) {
    const base = await requirementsApi.getDesign("p1");
    const [first, ...rest] = base.requirements;
    return { ...base, requirements: [{ ...first, ...over }, ...rest] };
  }

  it("can be set, and the one it has is the one pressed", async () => {
    const snapshot = await design({ priority: "should", priorityCorrected: false });
    const id = snapshot.requirements[0].id;
    const setRequirementPriority = show(snapshot);

    expect(screen.getByRole("button", { name: `Set ${id} to Should` }).getAttribute("aria-pressed")).toBe(
      "true",
    );
    fireEvent.click(screen.getByRole("button", { name: `Set ${id} to Must` }));

    expect(setRequirementPriority).toHaveBeenCalledWith({ id, priority: "must" });
  });

  it("does not ask for the priority it already has", async () => {
    const snapshot = await design({ priority: "should", priorityCorrected: false });
    const setRequirementPriority = show(snapshot);

    fireEvent.click(screen.getByRole("button", { name: `Set ${snapshot.requirements[0].id} to Should` }));

    expect(setRequirementPriority).not.toHaveBeenCalled();
  });

  it("says when a person set it, and that the sprint is planned again to use it", async () => {
    show(await design({ priority: "must", priorityCorrected: true }));

    expect(screen.getAllByText("Priority set by you").length).toBeGreaterThan(0);
    expect(screen.getByText(/Plan the sprint again in Sprint Planning to rank on it/)).toBeTruthy();
  });

  it("says where a priority that nobody set came from", async () => {
    show(await design({ priority: "should", priorityCorrected: false }));

    expect(screen.queryByText("Priority set by you")).toBeNull();
    expect(screen.getByText(/Read from the wording of your input/)).toBeTruthy();
  });
});

/**
 * A correction is kept against a requirement, and a change can reword the
 * requirement under it. Laid over anyway, the correction hid the change
 * (review item C1-8); left off in silence, the person's words would vanish.
 */
describe("a correction made to an earlier wording", () => {
  async function show(setAsideCorrection: string | null) {
    const base = await requirementsApi.getDesign("p1");
    const [first, ...rest] = base.requirements;
    render(
      <StageRequirements
        snapshot={{ ...base, requirements: [{ ...first, adjusted: false, setAsideCorrection }, ...rest] }}
        mutations={mutations}
        focusedRequirementId={first.id}
        onClearFocus={vi.fn()}
        onJump={vi.fn()}
        onOpenChat={vi.fn()}
        onContinueWithAnswers={vi.fn(async () => undefined)}
        onContinueWithAssumptions={vi.fn(async () => undefined)}
      />,
    );
  }

  it("is shown beside the requirement it no longer covers, and said not to apply", async () => {
    await show("A shopper pays by saved card.");

    // On the row, and again in the opened panel, where a narrow screen reads its tags.
    expect(screen.getAllByText("Changed since your correction")).toHaveLength(2);
    expect(
      screen.getByText(
        "This requirement changed after you corrected it, so your correction is not applied: A shopper pays by saved card.",
        { exact: false },
      ),
    ).toBeTruthy();
  });

  it("is not mentioned on a requirement that has none", async () => {
    await show(null);

    expect(screen.queryByText("Changed since your correction")).toBeNull();
    expect(screen.queryByText(/your correction is not applied/)).toBeNull();
  });
});

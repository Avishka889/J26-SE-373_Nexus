import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, within } from "@testing-library/react";
import { buildDeploySnapshot } from "../../fixtures/buildDeploySnapshot";
import { buildView } from "../../model/view";
import { StageReview } from "./StageReview";

afterEach(cleanup);

/**
 * Approving a High update and leaving any update out each need a note, and the
 * buttons were enabled without one, only for the server to refuse.
 */
describe("a decision on an update", () => {
  function show() {
    const snapshot = buildDeploySnapshot("p4", "deploy");
    const view = buildView(snapshot);
    const high = view.updates.find((one) => one.level === "high" && !one.decision?.decision);
    if (!high) throw new Error("the demo has an undecided High update");
    render(
      <StageReview
        snapshot={snapshot}
        view={{ ...view, decisionPending: true }}
        targets={[]}
        busy={false}
        goAhead={false}
        onGoAhead={vi.fn()}
        onDecideUpdate={vi.fn(async () => true)}
        onChooseTarget={vi.fn()}
        onChoosePolicy={vi.fn()}
        onOpenStage={vi.fn()}
        onOpenTesting={vi.fn()}
      />,
    );
    const row = document.querySelector(`[data-update-decision="${high.package}"]`) as HTMLElement;
    return within(row);
  }

  it("holds Approve on a High update and Leave out until the note is written", () => {
    const row = show();

    const approve = row.getByRole("button", { name: "Approve" }) as HTMLButtonElement;
    const leaveOut = row.getByRole("button", { name: "Leave out" }) as HTMLButtonElement;
    expect(approve.disabled).toBe(true);
    expect(leaveOut.disabled).toBe(true);
    expect(approve.title).toMatch(/what you checked/);

    fireEvent.change(row.getByRole("textbox"), { target: { value: "read the changelog" } });

    expect(approve.disabled).toBe(false);
    expect(leaveOut.disabled).toBe(false);
  });
});

/**
 * A pipeline whose validators failed or never ran shipped all the same: its
 * validity was computed and read by no guard (review item C4-8).
 */
describe("what stops this release", () => {
  it("names the pipeline guard and opens the stage that shows its validation", () => {
    const snapshot = buildDeploySnapshot("p4", "deploy");
    const view = buildView(snapshot);
    const onOpenStage = vi.fn();
    const screen = render(
      <StageReview
        snapshot={snapshot}
        view={{
          ...view,
          decisionPending: true,
          blocking: [
            {
              code: "G7",
              message: "the generated pipeline did not validate: Dockerfile, hadolint failed (DL3008)",
              updateId: null,
            },
          ],
        }}
        targets={[]}
        busy={false}
        goAhead={false}
        onGoAhead={vi.fn()}
        onDecideUpdate={vi.fn(async () => true)}
        onChooseTarget={vi.fn()}
        onChoosePolicy={vi.fn()}
        onOpenStage={onOpenStage}
        onOpenTesting={vi.fn()}
      />,
    );

    expect(screen.getByText("Pipeline validation")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Go to CI/CD Pipeline" }));
    expect(onOpenStage).toHaveBeenCalledWith("pipeline-generation");
  });
});

describe("a security finding that stops the release", () => {
  // Decided on the Testing page, so that is where the review sends the reader (G8).
  it("names the guard and opens Testing & Security", () => {
    const snapshot = buildDeploySnapshot("p4", "deploy");
    const view = buildView(snapshot);
    const onOpenTesting = vi.fn();
    const screen = render(
      <StageReview
        snapshot={snapshot}
        view={{
          ...view,
          decisionPending: true,
          blocking: [
            {
              code: "G8",
              message: "CWE-89 SQL injection, High (8.1), at orders.ts:36 is open",
              updateId: null,
            },
          ],
        }}
        targets={[]}
        busy={false}
        goAhead={false}
        onGoAhead={vi.fn()}
        onDecideUpdate={vi.fn(async () => true)}
        onChooseTarget={vi.fn()}
        onChoosePolicy={vi.fn()}
        onOpenStage={vi.fn()}
        onOpenTesting={onOpenTesting}
      />,
    );

    expect(screen.getByText("Security findings")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Go to Testing & Security" }));
    expect(onOpenTesting).toHaveBeenCalled();
  });
});

describe("what a release ships", () => {
  // The review did not say which code went out, or under which tests (review item C4-7).
  it("names the code version and the test version its approval covers", () => {
    const snapshot = {
      ...buildDeploySnapshot("p4", "deploy"),
      deployVersion: 3,
      deployedCodeVersion: 2,
      analysedTestVersion: 4,
    };

    const screen = render(
      <StageReview
        snapshot={snapshot}
        view={buildView(snapshot)}
        targets={[]}
        busy={false}
        goAhead={false}
        onGoAhead={vi.fn()}
        onDecideUpdate={vi.fn(async () => true)}
        onChooseTarget={vi.fn()}
        onChoosePolicy={vi.fn()}
        onOpenStage={vi.fn()}
        onOpenTesting={vi.fn()}
      />,
    );

    expect(
      screen.getByText(
        "Deploy version 3 ships code version 2, with the tests approved at test version 4.",
      ),
    ).toBeTruthy();
  });
});


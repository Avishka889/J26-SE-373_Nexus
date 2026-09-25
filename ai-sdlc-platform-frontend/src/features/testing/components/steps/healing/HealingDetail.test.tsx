import { afterEach, describe, expect, it, vi } from "vitest";
import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { failures } from "../../../fixtures/failures";
import type { ViewFailure } from "../../../model/view";
import { HealingDetail } from "./HealingDetail";

afterEach(cleanup);

const awaiting = failures.find((one) => one.state === "awaiting-approval" && one.repair)!;

function show(failure: ViewFailure) {
  const handlers = { onApprove: vi.fn(), onReject: vi.fn(), onOpenCode: vi.fn() };
  render(
    <HealingDetail failure={failure} showDetail onBack={vi.fn()} onOpenFile={vi.fn()} {...handlers} />,
  );
  return handlers;
}

describe("a decision on a repair", () => {
  // Deciding was recorded and never read back, so the page stayed as it was
  // and offered the same decision again.
  it("is shown once made, and not offered again", () => {
    show({
      ...awaiting,
      decision: { decision: "approved", by: "Sam", at: "2026-10-04T10:00:00Z", build: 1 },
    });

    expect(screen.getByText(/Sam kept this/)).toBeTruthy();
    expect(screen.queryByRole("button", { name: /keep the repair/i })).toBeNull();
  });

  it("is offered while none is in", () => {
    const { onApprove } = show(awaiting);

    fireEvent.click(screen.getByRole("button", { name: /keep the repair/i }));

    expect(onApprove).toHaveBeenCalledWith(awaiting.id);
  });
});

describe("a regression", () => {
  // Requesting changes rewrote tests that then failed again, and nothing on
  // the page led to the code, which is what has to change.
  it("leads to Code Generation", () => {
    const { onOpenCode } = show({ ...awaiting, triage: "regression", state: "escalated", repair: undefined });

    fireEvent.click(screen.getByRole("button", { name: /open code generation/i }));

    expect(onOpenCode).toHaveBeenCalled();
  });
});

describe("what keeping a repair does", () => {
  // Keeping was only recorded, and the page said so: "it does not change the
  // suite". It now writes the repair into the test file, and says that first.
  it("is said before it is done: the repair goes into the test file", () => {
    show(awaiting);

    expect(screen.getByText(/writes the repair into the test file/)).toBeTruthy();
  });

  it("can be undone: a kept repair can be put back", () => {
    const { onReject } = show({
      ...awaiting,
      decision: { decision: "approved", by: "Sam", at: "2026-10-04T10:00:00Z", build: 1 },
    });

    expect(screen.getByText(/The test file now carries it/)).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: /put the test back/i }));

    expect(onReject).toHaveBeenCalledWith(awaiting.id);
  });

  it("leaves a rejected repair's test as written, with nothing more to do", () => {
    show({
      ...awaiting,
      decision: { decision: "rejected", by: "Sam", at: "2026-10-04T10:00:00Z", build: 1 },
    });

    expect(screen.getByText(/The test stays as written/)).toBeTruthy();
    expect(screen.queryByRole("button", { name: /put the test back/i })).toBeNull();
  });
});

describe("a repair to an API test", () => {
  // Every run writes it again from the contract, so a kept repair would not last.
  it("is not offered for keeping, and says why", () => {
    const { onReject } = show({ ...awaiting, rewrittenEachRun: true });

    expect(screen.queryByRole("button", { name: /keep the repair/i })).toBeNull();
    expect(screen.getByText(/every run writes again from the contract/)).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: /reject it/i }));
    expect(onReject).toHaveBeenCalledWith(awaiting.id);
  });
});

describe("a failing test no repair will fix", () => {
  const unclassified: ViewFailure = {
    ...awaiting,
    triage: "unclassified",
    state: "escalated",
    repair: undefined,
    decision: undefined,
  };

  function decide(failure: ViewFailure, answer: unknown = undefined) {
    const onDecideTest = vi.fn(async () => answer);
    render(
      <HealingDetail
        failure={failure}
        showDetail
        onBack={vi.fn()}
        onOpenFile={vi.fn()}
        onApprove={vi.fn()}
        onReject={vi.fn()}
        onOpenCode={vi.fn()}
        onDecideTest={onDecideTest}
      />,
    );
    return onDecideTest;
  }

  it("is quarantined only with a reason", () => {
    const onDecideTest = decide(unclassified);

    fireEvent.click(screen.getByRole("button", { name: /quarantine with a reason/i }));
    const confirm = screen.getByRole("button", { name: /quarantine it/i }) as HTMLButtonElement;
    expect(confirm.disabled).toBe(true);
    fireEvent.change(screen.getByLabelText(/why this test is quarantined/i), {
      target: { value: "asserts a title the design dropped" },
    });
    fireEvent.click(confirm);

    expect(onDecideTest).toHaveBeenCalledWith(
      unclassified.id,
      "quarantined",
      "asserts a title the design dropped",
    );
  });

  it("keeps the reason typed when the server refuses", async () => {
    const onDecideTest = decide(unclassified, null);

    fireEvent.click(screen.getByRole("button", { name: /quarantine with a reason/i }));
    fireEvent.change(screen.getByLabelText(/why this test is quarantined/i), {
      target: { value: "asserts a title the design dropped" },
    });
    fireEvent.click(screen.getByRole("button", { name: /quarantine it/i }));
    await waitFor(() => expect(onDecideTest).toHaveBeenCalled());
    // The refusal settles before what is left on screen is read.
    await act(async () => {});

    expect(
      (screen.getByLabelText(/why this test is quarantined/i) as HTMLTextAreaElement).value,
    ).toBe("asserts a title the design dropped");
  });

  it("offers nothing over a kept repair, which is in the test file already", () => {
    decide({
      ...unclassified,
      decision: { decision: "approved", at: "2026-10-05T10:00:00Z", by: "Ana", build: 2 },
    });

    expect(screen.queryByRole("button", { name: /quarantine with a reason/i })).toBeNull();
  });

  it("can be asked for again, unless the contract writes it on every run", () => {
    decide({ ...unclassified, rewrittenEachRun: true });

    expect(screen.queryByRole("button", { name: /write it again/i })).toBeNull();
  });

  it("once quarantined, says so and can be restored", () => {
    const onDecideTest = decide({
      ...unclassified,
      state: "quarantined",
      setAside: { decision: "quarantined", by: "Ana", at: "2026-10-05T10:00:00Z", note: "wrong title" },
    });

    expect(screen.getByText(/Ana quarantined this test/)).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: /restore the test/i }));

    expect(onDecideTest).toHaveBeenCalledWith(unclassified.id, "restored", undefined);
  });
});

/**
 * A failure nothing classified, as a first run's are.
 *
 * It showed the test's whole name in monospace broken mid-word, one of its
 * three requirements, and no word of why it failed; and it offered only to
 * quarantine the test or have it written again, which are both for a test that
 * is wrong, when the code was.
 */
describe("a failure nothing has classified", () => {
  const unclassified: ViewFailure = {
    ...awaiting,
    repair: undefined,
    decision: undefined,
    note: undefined,
    triage: "unclassified",
    state: "escalated",
    test: "As a receptionist, I can record a doctor US-2 AC-2-1: given no doctor, when one is saved, then it is retrievable",
    label: {
      ref: "US-2 AC-2-1",
      story: "As a receptionist, I can record a doctor",
      text: "given no doctor, when one is saved, then it is retrievable",
    },
    message: "AssertionError: expected 404 to be less than 400",
    reason: "No earlier tested version to compare with, so nothing yet tells a stale test from a regression.",
    requirements: ["R-1", "R-21", "R-27"],
    file: "apps/api/src/__tests__/US-2.criteria.test.ts",
    line: 37,
  };

  it("says what the runner said, under its own heading", () => {
    show(unclassified);

    expect(screen.getByText("Why it failed")).toBeTruthy();
    expect(screen.getByText("AssertionError: expected 404 to be less than 400")).toBeTruthy();
  });

  it("is headed by its reference and its story, with the criterion as prose", () => {
    show(unclassified);

    const title = screen.getByRole("heading", { name: /US-2 AC-2-1/ });
    expect(title.textContent).toContain("As a receptionist, I can record a doctor");
    expect(title.innerHTML).not.toContain("break-all");
    expect(screen.getByText("given no doctor, when one is saved, then it is retrievable")).toBeTruthy();
  });

  it("names every requirement it protects", () => {
    show(unclassified);

    expect(screen.getByText(/protects R-1, R-21, R-27/)).toBeTruthy();
  });

  it("opens the test file at the failing line", () => {
    const onOpenFile = vi.fn();
    render(
      <HealingDetail
        failure={unclassified}
        showDetail
        onBack={vi.fn()}
        onOpenFile={onOpenFile}
        onApprove={vi.fn()}
        onReject={vi.fn()}
        onOpenCode={vi.fn()}
      />,
    );

    fireEvent.click(screen.getByRole("button", { name: /US-2\.criteria\.test\.ts:37/ }));

    expect(onOpenFile).toHaveBeenCalledWith("apps/api/src/__tests__/US-2.criteria.test.ts", 37, expect.any(String));
  });

  it("leads to Code Generation, for when the test is right and the code is not", () => {
    const { onOpenCode } = show(unclassified);

    expect(screen.getByText(/If the test is right, the code has to change/)).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: /open code generation/i }));

    expect(onOpenCode).toHaveBeenCalled();
  });
});

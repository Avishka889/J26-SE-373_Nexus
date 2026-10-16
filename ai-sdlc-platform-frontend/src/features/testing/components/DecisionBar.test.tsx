import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { buildTestSnapshot } from "../fixtures/buildTestSnapshot";
import { buildView } from "../model/view";
import type { TestSnapshot } from "../api/types";
import type { TestingView } from "../model/view";
import { DecisionBar } from "./DecisionBar";

afterEach(cleanup);

/**
 * The test review's decision, while a generated app's test is red.
 *
 * Book Tracker's was approved over a failing test, and Deployment's staging
 * build refused the candidate for it. The server refuses that approval now, so
 * the bar holds Approve and says why, and changes can still be requested.
 */
function show(target: string) {
  const data = { ...buildTestSnapshot("p1", "awaiting", 1), target } as TestSnapshot;
  const onApprove = vi.fn();
  render(
    <DecisionBar
      view={buildView({ data, reviewer: "you" })}
      onApprove={onApprove}
      onRequestChanges={vi.fn()}
    />,
  );
  return { onApprove };
}

describe("the test review's decision", () => {
  it("holds Approve while a generated app's test fails, and says which", () => {
    show("generated");

    const approve = screen.getByRole("button", { name: /approve the tests/i });
    expect((approve as HTMLButtonElement).disabled).toBe(true);
    expect(screen.getByText(/Deployment runs the same tests and would refuse this build/)).toBeTruthy();
    const changes = screen.getByRole("button", { name: /request changes/i });
    expect((changes as HTMLButtonElement).disabled).toBe(false);
  });

  it("leaves a sample's review to the person, since its failures are seeded", () => {
    show("sample:java");

    const approve = screen.getByRole("button", { name: /approve the tests/i });
    expect((approve as HTMLButtonElement).disabled).toBe(false);
  });
});

/** A run in which nothing ran said "every proof passed" over an empty table. */
describe("the test review's decision over a run that proved nothing", () => {
  function unprovenView(unproven: string[]): TestingView {
    return {
      unproven,
      inbox: { awaiting: 0, regressions: 0, unclassified: 0, brittle: 0, healed: 0 },
      findingCounts: { toResolve: 0 },
      failingTests: [],
      superseded: null,
      build: 2,
    } as unknown as TestingView;
  }

  function showUnproven(unproven: string[]) {
    render(
      <DecisionBar view={unprovenView(unproven)} onApprove={vi.fn()} onRequestChanges={vi.fn()} />,
    );
  }

  it("lists what the run did not prove, and does not say every proof passed", () => {
    showUnproven(["no test ran: install failed"]);

    expect(screen.queryByText(/every proof passed/)).toBeNull();
    expect(screen.getByText(/no test ran: install failed/)).toBeTruthy();
  });

  it("says every proof passed when nothing is outstanding", () => {
    showUnproven([]);

    expect(screen.getByText(/every proof passed/)).toBeTruthy();
  });
});

/**
 * Why Approve is held, in a line. It quoted the first failing test's whole
 * name, a story and a criterion of forty words, and the bar grew to seven
 * lines; pinned to the bottom of the page, as every other phase's is, that is
 * a third of the screen.
 */
describe("why the test review's Approve is held", () => {
  function held(names: string[]) {
    const view = buildView({ data: buildTestSnapshot("p1", "awaiting", 1), reviewer: "you" });
    const onOpenStage = vi.fn();
    render(
      <DecisionBar
        view={{ ...view, failingTests: names, failingRefs: names.map((one) => one.split(":")[0]) }}
        onApprove={vi.fn()}
        onRequestChanges={vi.fn()}
        onOpenStage={onOpenStage}
      />,
    );
    return { onOpenStage };
  }

  it("names the failing tests by reference, not by their whole names", () => {
    held(["US-2 AC-2-1: given a long thing", "US-2 AC-2-3: given another", "US-3 AC-3-2: given a third"]);

    expect(
      screen.getByText(
        "3 tests fail (US-2 AC-2-1, US-2 AC-2-3 and US-3 AC-3-2). Deployment runs the same tests and would refuse this build.",
      ),
    ).toBeTruthy();
    expect(screen.queryByText(/given a long thing/)).toBeNull();
  });

  it("names three and counts the rest", () => {
    held(["A-1: x", "A-2: x", "A-3: x", "A-4: x", "A-5: x"]);

    expect(screen.getByText(/^5 tests fail \(A-1, A-2, A-3 and 2 more\)\./)).toBeTruthy();
  });

  it("leads to Self Healing, where each is decided", () => {
    const { onOpenStage } = held(["US-2 AC-2-1: given a long thing"]);

    screen.getByRole("button", { name: "See why in Self Healing" }).click();

    expect(onOpenStage).toHaveBeenCalledWith("self-healing");
  });
});

describe("the note a change request at the test review carries", () => {
  // It asked "Which tests or findings have to change", and nothing reads the
  // answer: the next run is written from the criteria and the contract again.
  it("is asked for as a reason to run again, and says what it is not", () => {
    const data = { ...buildTestSnapshot("p1", "awaiting", 1), target: "sample:java" } as TestSnapshot;
    render(
      <DecisionBar view={buildView({ data, reviewer: "you" })} onApprove={vi.fn()} onRequestChanges={vi.fn()} />,
    );

    fireEvent.click(screen.getByRole("button", { name: /request changes/i }));

    expect(screen.getByLabelText("Why the tests should run again")).toBeTruthy();
    expect(
      screen.getByPlaceholderText(/kept on the record\. It does not steer how the tests are written/),
    ).toBeTruthy();
  });
});

describe("what the bar says is outstanding while tests fail", () => {
  // The failing tests were said twice: once as "3 failures not yet called a
  // stale test or a regression" and once by name, and on a laptop the pinned
  // bar ran to five lines over a stage 270 pixels tall.
  it("names the failing tests once, by reference", () => {
    const view = buildView({ data: buildTestSnapshot("p1", "awaiting", 1), reviewer: "you" });
    render(
      <DecisionBar
        view={{
          ...view,
          unproven: [],
          failingTests: ["US-2 AC-2-1: given a long thing"],
          failingRefs: ["US-2 AC-2-1"],
          inbox: { ...view.inbox, awaiting: 0, regressions: 2, unclassified: 1 },
          findingCounts: { ...view.findingCounts, toResolve: 0 },
        }}
        onApprove={vi.fn()}
        onRequestChanges={vi.fn()}
      />,
    );

    expect(screen.getByText(/1 test fails \(US-2 AC-2-1\)/)).toBeTruthy();
    expect(screen.queryByText(/Outstanding:/)).toBeNull();
  });

  it("still counts them as outstanding where they do not hold the approval", () => {
    const view = buildView({ data: buildTestSnapshot("p1", "awaiting", 1), reviewer: "you" });
    render(
      <DecisionBar
        view={{
          ...view,
          unproven: [],
          failingTests: [],
          failingRefs: [],
          inbox: { ...view.inbox, awaiting: 0, regressions: 2, unclassified: 1 },
          findingCounts: { ...view.findingCounts, toResolve: 0 },
        }}
        onApprove={vi.fn()}
        onRequestChanges={vi.fn()}
      />,
    );

    expect(
      screen.getByText(
        "Outstanding: 2 regressions needing a code change · 1 failure not yet called a stale test or a regression",
      ),
    ).toBeTruthy();
  });
});


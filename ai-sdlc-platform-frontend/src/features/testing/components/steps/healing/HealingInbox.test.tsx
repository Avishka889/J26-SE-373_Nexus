import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, render, screen, within } from "@testing-library/react";
import { buildTestSnapshot } from "../../../fixtures/buildTestSnapshot";
import { failures } from "../../../fixtures/failures";
import { buildView, type ViewFailure } from "../../../model/view";
import { HealingInbox } from "./HealingInbox";

afterEach(cleanup);

const base = failures[0];

function row(id: string, ref: string, message: string): ViewFailure {
  return {
    ...base,
    id,
    repair: undefined,
    triage: "unclassified",
    state: "escalated",
    test: `As a receptionist, I can record a doctor with a name, a specialty and the weekdays they work ${ref}: given a long thing, when another, then a third`,
    label: {
      ref,
      story: "As a receptionist, I can record a doctor with a name, a specialty and the weekdays they work",
      text: "given a long thing, when another, then a third",
    },
    message,
    reason: "No earlier tested version to compare with, so nothing yet tells a stale test from a regression.",
  };
}

/**
 * Three failures in one story read as the same row three times: each showed
 * the story's sentence, cut off before the criterion that tells them apart,
 * over the same sentence about there being no earlier version.
 */
describe("the failure inbox's rows", () => {
  function inbox(list: ViewFailure[]) {
    render(
      <HealingInbox
        view={buildView({ data: buildTestSnapshot("p1", "awaiting", 1), reviewer: "you" })}
        filter="attention"
        onFilter={vi.fn()}
        list={list}
        selectedId={list[0]?.id}
        onSelect={vi.fn()}
        showDetail={false}
        onShowDetail={vi.fn()}
      />,
    );
  }

  it("lead with the reference, which is what tells two failures of one story apart", () => {
    inbox([
      row("a", "US-2 AC-2-1", "AssertionError: expected 404 to be less than 400"),
      row("b", "US-2 AC-2-3", "AssertionError: expected 'Cardiology' to be 'Neurology'"),
    ]);

    const rows = screen.getAllByRole("button", { name: /US-2 AC-2-/ });
    expect(rows).toHaveLength(2);
    expect(within(rows[0]).getByText("US-2 AC-2-1")).toBeTruthy();
    expect(within(rows[1]).getByText("US-2 AC-2-3")).toBeTruthy();
  });

  it("say what the runner said, where the reason every row shared was", () => {
    inbox([row("a", "US-2 AC-2-1", "AssertionError: expected 404 to be less than 400")]);

    expect(screen.getByText("AssertionError: expected 404 to be less than 400")).toBeTruthy();
    expect(screen.queryByText(/No earlier tested version/)).toBeNull();
  });

  it("fall back to the reason for a failure with no message", () => {
    inbox([row("a", "US-2 AC-2-1", "")]);

    expect(screen.getByText(/No earlier tested version/)).toBeTruthy();
  });
});

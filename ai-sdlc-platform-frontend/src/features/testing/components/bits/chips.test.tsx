import { afterEach, describe, expect, it } from "vitest";
import { cleanup, render, screen } from "@testing-library/react";
import { failures } from "../../fixtures/failures";
import { SeverityChip, StateChip } from "./chips";

afterEach(cleanup);

/**
 * A finding scored CVSS 0 has severity "none": the contract allows it, and the
 * page knew four severities, so the chip rendered an undefined icon and took
 * the Testing page down.
 */
describe("a finding with no severity", () => {
  it("renders as None", () => {
    render(<SeverityChip severity="none" />);

    expect(screen.getByText("None")).toBeTruthy();
  });
});

/**
 * An escalated failure without an owner: nothing assigns a live failure to
 * anyone, and the badge said "With the developer" all the same.
 */
describe("an escalated failure", () => {
  const escalated = failures[0];

  it("says a regression needs a code change, naming no one", () => {
    render(<StateChip failure={{ ...escalated, state: "escalated", triage: "regression", owner: undefined }} />);

    expect(screen.getByText("Needs a code change")).toBeTruthy();
    expect(screen.queryByText(/^With/)).toBeNull();
  });

  it("names the owner when one is known", () => {
    render(<StateChip failure={{ ...escalated, state: "escalated", owner: "A. Chen" }} />);

    expect(screen.getByText("With A. Chen")).toBeTruthy();
  });
});

import { afterEach, describe, expect, it } from "vitest";
import { cleanup, render, screen } from "@testing-library/react";
import { buildTestSnapshot } from "../../fixtures/buildTestSnapshot";
import { buildView, type TestingView } from "../../model/view";
import { StepGeneration } from "./StepGeneration";

afterEach(cleanup);

const base = buildView({ data: buildTestSnapshot("p1", "awaiting", 1), reviewer: "you" });

function stage(generation: Partial<TestingView["generation"]>, skipped = 0) {
  render(
    <StepGeneration
      view={{
        ...base,
        totals: { ...base.totals, run: 30, skipped },
        generation: {
          summary: "",
          sources: { criteria: 6, filled: 6, contract: 9, shipped: 15 },
          gaps: [],
          gapsReported: 0,
          ...generation,
        },
      }}
    />,
  );
}

/**
 * Test Generation read the run's totals and nothing of what the generator
 * said. Over five contract obligations nothing implements it read "Every
 * criterion in scope has a test", and it called thirty tests of three kinds
 * the work of "two places".
 */
describe("the test generation stage", () => {
  it("says where the suite's tests came from", () => {
    stage({});

    expect(screen.getByText("From acceptance criteria")).toBeTruthy();
    expect(screen.getByText("6 written by the model")).toBeTruthy();
    expect(screen.getByText("From the API contract")).toBeTruthy();
    expect(screen.getByText("Shipped with the code")).toBeTruthy();
    expect(screen.queryByText(/Tests come from two places/)).toBeNull();
  });

  it("lists each contract obligation no test can assert, with its reason", () => {
    stage({
      gaps: [
        {
          endpointId: "post-doctors-id-manage",
          kind: "no-way-to-create",
          detail: "the contract declares POST /doctors/{id}/manage but no POST on /doctors",
        },
        {
          endpointId: "post-doctors-id-manage",
          kind: "auth-not-implemented",
          detail: "the contract restricts this to Receptionist and the application has no authentication",
        },
      ],
    });

    expect(screen.getByText("2 contract obligations no test can assert")).toBeTruthy();
    expect(screen.getByText("Nothing creates one")).toBeTruthy();
    expect(screen.getByText("No sign-in to refuse")).toBeTruthy();
    expect(screen.getByText(/the contract declares POST \/doctors\/\{id\}\/manage but no POST on \/doctors/)).toBeTruthy();
    expect(screen.getAllByText("post-doctors-id-manage")).toHaveLength(2);
    expect(screen.queryByText(/Every criterion in scope has a test/)).toBeNull();
  });

  it("says how many the stage reported, for a run made before they were listed", () => {
    stage({ gapsReported: 5 });

    expect(screen.getByText("5 contract obligations no test can assert")).toBeTruthy();
    expect(screen.getByText(/This run was made before each was listed here/)).toBeTruthy();
    expect(screen.queryByText(/Every criterion in scope has a test/)).toBeNull();
  });

  it("says everything is covered only when nothing is declared and nothing is out of reach", () => {
    stage({});

    expect(screen.getByText("Every criterion has a test, and the contract obliges nothing a test cannot reach")).toBeTruthy();
  });

  it("counts the criteria declared and not yet written apart from the contract's obligations", () => {
    stage({}, 2);

    expect(screen.getByText("2 criteria declared and not yet written")).toBeTruthy();
  });

  it("shows what the stage said of itself", () => {
    stage({ summary: "9 contract tests, 5 contract obligations nothing implements" });

    expect(screen.getByText("9 contract tests, 5 contract obligations nothing implements")).toBeTruthy();
  });
});

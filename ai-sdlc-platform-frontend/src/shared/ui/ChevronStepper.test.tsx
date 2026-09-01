import { afterEach, describe, expect, it } from "vitest";
import { cleanup, render, screen } from "@testing-library/react";
import { ChevronStepper } from "./ChevronStepper";

afterEach(cleanup);

/**
 * A stage's state was its colour alone, so a reader who cannot tell amber from
 * emerald, and every screen reader, had no way to know which stage had failed.
 */
describe("a stage chevron", () => {
  it("says its state in words, not only in colour", () => {
    render(
      <ChevronStepper
        steps={[
          { id: "a", label: "Requirements Analysis", status: "complete" },
          { id: "b", label: "Domain Model", status: "failed" },
          { id: "c", label: "UML Diagrams", status: "generating" },
          { id: "d", label: "Wireframes", status: "future" },
        ]}
        onStepClick={() => undefined}
      />,
    );

    expect(screen.getByRole("button", { name: "Requirements Analysis, complete" })).toBeTruthy();
    expect(screen.getByRole("button", { name: "Domain Model, failed" })).toBeTruthy();
    expect(screen.getByRole("button", { name: "UML Diagrams, generating" })).toBeTruthy();
    expect(screen.getByRole("button", { name: "Wireframes, not reached yet" })).toBeTruthy();
  });

  // Code's agreement errors were a bare "2" on the conversation button; on
  // their stage, a screen reader hears what the number counts.
  it("says what its count counts", () => {
    render(
      <ChevronStepper
        steps={[
          {
            id: "a",
            label: "Contract Agreement",
            status: "complete",
            badge: 2,
            badgeLabel: "2 agreement errors",
          },
        ]}
        onStepClick={() => undefined}
      />,
    );

    expect(
      screen.getByRole("button", { name: "Contract Agreement, complete, 2 agreement errors" }),
    ).toBeTruthy();
  });
});

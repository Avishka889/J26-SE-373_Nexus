import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, render, screen } from "@testing-library/react";
import { PhaseNotStarted } from "./EmptyStates";

afterEach(cleanup);

/**
 * The page a reviewer lands on from Code Generation's "Continue to Testing & Security".
 *
 * Before a first run it said "Waiting on Code Generation - no build has been
 * produced yet", with a button back to Code Generation, whatever the code review
 * had decided: a reviewer who had just approved the build was sent back to it.
 */
function show(codeApproved: boolean) {
  const onOpenCode = vi.fn();
  render(
    <PhaseNotStarted projectName="Book Tracker" codeApproved={codeApproved} onOpenCode={onOpenCode} />,
  );
  return { onOpenCode };
}

describe("a testing phase that has not run", () => {
  // The run starts from the header, as Code Generation's does; the card says
  // where, rather than offering a second button that does the same.
  it("points to Run tests in the header once the code review approved the build", () => {
    show(true);
    expect(screen.getByText(/the code review approved this build/i)).toBeTruthy();
    expect(screen.getByText(/Run tests at the top of this page/)).toBeTruthy();
    expect(screen.queryByText(/no build has been produced/i)).toBeNull();
    expect(screen.queryByRole("button")).toBeNull();
  });

  it("points back to Code Generation while its review has approved nothing", () => {
    const { onOpenCode } = show(false);
    expect(screen.getByText(/its review has not approved a build yet/i)).toBeTruthy();
    expect(screen.queryByRole("button", { name: "Run tests" })).toBeNull();
    screen.getByRole("button", { name: /open code generation/i }).click();
    expect(onOpenCode).toHaveBeenCalledOnce();
  });
});

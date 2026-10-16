import { afterEach, describe, expect, it, vi } from "vitest";
import { act, cleanup, fireEvent, render, screen } from "@testing-library/react";
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
  const onRun = vi.fn();
  render(
    <PhaseNotStarted
      projectName="Book Tracker"
      codeApproved={codeApproved}
      running={false}
      onOpenCode={onOpenCode}
      onRun={onRun}
    />,
  );
  return { onOpenCode, onRun };
}

describe("a testing phase that has not run", () => {
  it("offers the first run once the code review approved the build", () => {
    const { onRun } = show(true);
    expect(screen.getByText(/the code review approved this build/i)).toBeTruthy();
    expect(screen.queryByText(/no build has been produced/i)).toBeNull();
    expect(screen.queryByRole("button", { name: /open code generation/i })).toBeNull();
    screen.getByRole("button", { name: "Run tests" }).click();
    expect(onRun).toHaveBeenCalledOnce();
  });

  it("stays busy on Run tests until the server answers, so a second click sends nothing", async () => {
    // Reported from the live run: the click seemed to do nothing until the
    // server answered, so it was clicked again.
    let answer!: () => void;
    const onRun = vi.fn(() => new Promise<void>((resolve) => (answer = resolve)));
    render(
      <PhaseNotStarted
        projectName="Movie Tracker"
        codeApproved
        running={false}
        onOpenCode={vi.fn()}
        onRun={onRun}
      />,
    );
    const button = screen.getByRole("button", { name: "Run tests" }) as HTMLButtonElement;

    fireEvent.click(button);
    fireEvent.click(button);

    expect(onRun).toHaveBeenCalledOnce();
    expect(button.getAttribute("aria-busy")).toBe("true");
    await act(async () => answer());
    expect(button.getAttribute("aria-busy")).toBeNull();
  });

  it("points back to Code Generation while its review has approved nothing", () => {
    const { onOpenCode } = show(false);
    expect(screen.getByText(/its review has not approved a build yet/i)).toBeTruthy();
    expect(screen.queryByRole("button", { name: "Run tests" })).toBeNull();
    screen.getByRole("button", { name: /open code generation/i }).click();
    expect(onOpenCode).toHaveBeenCalledOnce();
  });
});

import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { PhaseNotRun, PhaseWaitingOnTesting } from "./EmptyStates";
import { DeploymentHeader } from "./DeploymentHeader";
import type { ReleaseTargetOption } from "../api/types";

afterEach(cleanup);

const TARGETS: ReleaseTargetOption[] = [
  { id: "local", label: "This machine, in containers", usable: true, reason: "" },
  {
    id: "cloud",
    label: "Vercel and Render, through GitHub Actions",
    usable: false,
    reason: "connect Render in Settings first",
  },
];

function firstRun(testedCode: number, currentCode: number) {
  const handlers = {
    onRun: vi.fn(),
    onChooseTarget: vi.fn(),
    onChooseScope: vi.fn(async () => true),
    onOpenTesting: vi.fn(),
  };
  render(
    <PhaseNotRun
      busy={false}
      testVersion={2}
      testedCode={testedCode}
      currentCode={currentCode}
      targets={TARGETS}
      target="local"
      scopePackages={[]}
      {...handlers}
    />,
  );
  return handlers;
}

/**
 * The first-run screen said the approved tests measured the current code
 * whatever they measured, and where a release goes, and what to analyse, could
 * be chosen only after the analysis that depends on them. Then newer code with
 * no approved tests took the run away, though the tested code may ship.
 */
describe("before the first analysis", () => {
  it("asks where the release goes and what to analyse, before it runs", () => {
    const { onChooseScope } = firstRun(3, 3);

    expect(screen.getByText(/measured code version 3, the current code/)).toBeTruthy();
    expect((screen.getByRole("radio", { name: /this machine/i }) as HTMLInputElement).checked).toBe(true);
    const cloud = screen.getByRole("radio", { name: /vercel and render/i }) as HTMLInputElement;
    expect(cloud.disabled).toBe(true);
    expect(screen.getByText(/Not available: connect Render in Settings first/)).toBeTruthy();

    fireEvent.change(screen.getByLabelText(/analyse/i), { target: { value: "express, zod express" } });
    fireEvent.click(screen.getByRole("button", { name: "Save" }));
    expect(onChooseScope).toHaveBeenCalledWith(["express", "zod"]);
  });

  it("runs on the tested code while newer code waits for its own tests", () => {
    const { onRun, onOpenTesting } = firstRun(3, 5);

    expect(screen.getByText(/so this phase analyses and releases version 3/)).toBeTruthy();
    expect(screen.getByText(/Code version 5 is newer and waits for its own tests/)).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: /analyse updates/i }));
    expect(onRun).toHaveBeenCalled();
    fireEvent.click(screen.getByRole("button", { name: /open testing/i }));
    expect(onOpenTesting).toHaveBeenCalled();
  });
});

describe("analysing again", () => {
  it("offers the target beside the button, before the run", async () => {
    const onChooseTarget = vi.fn();
    render(
      <DeploymentHeader
        progress={50}
        isDark={false}
        canRun
        running={false}
        version={2}
        onRun={vi.fn()}
        targets={TARGETS}
        target="local"
        onChooseTarget={onChooseTarget}
      />,
    );

    const select = screen.getByRole("combobox", { name: /release to/i });
    expect(select.textContent).toBe("This machine");
    await userEvent.click(select);
    // Why it cannot be used is in the list, where a touch screen shows it too:
    // it was a tooltip.
    const cloud = await screen.findByRole("option", { name: /the cloud/i });
    expect(cloud.getAttribute("aria-disabled")).toBe("true");
    expect(cloud.textContent).toContain("Unavailable: connect Render in Settings first");
    await userEvent.click(cloud);
    expect(onChooseTarget).not.toHaveBeenCalled();
  });
});

describe("before any approval of the app's tests", () => {
  // A sample's approved run unlocked Deployment of the app (review item C3-3).
  it("says only an approved run on the generated app counts", () => {
    render(<PhaseWaitingOnTesting projectName="Movie Tracker" onOpenTesting={vi.fn()} />);

    expect(screen.getByText(/no test run of the generated app has been approved yet/)).toBeTruthy();
    expect(screen.getByText(/An approved run on a sample does not count/)).toBeTruthy();
  });
});

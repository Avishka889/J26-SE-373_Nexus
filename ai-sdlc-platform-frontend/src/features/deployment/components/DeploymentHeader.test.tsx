import { afterEach, describe, expect, it, vi } from "vitest";
import { act, cleanup, render, screen } from "@testing-library/react";
import { DeploymentHeader } from "./DeploymentHeader";

afterEach(() => {
  cleanup();
  vi.useRealTimers();
});

/**
 * Every stage of a run showed a spinner at once, so nothing said which one was
 * working or for how long, as on Testing during the live run.
 */
describe("the deployment header while a run works", () => {
  it("names the stage the run is working on, and for how long", () => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date("2026-10-06T06:01:05Z"));
    render(
      <DeploymentHeader
        progress={20}
        isDark={false}
        canRun={false}
        running
        version={1}
        onRun={vi.fn()}
        working={{ label: "Changelog Analysis", since: "2026-10-06T06:00:00Z" }}
      />,
    );

    expect(screen.getByText("Working on Changelog Analysis, 1m 5s so far")).toBeTruthy();
    act(() => {
      vi.advanceTimersByTime(1000);
    });
    expect(screen.getByText("Working on Changelog Analysis, 1m 6s so far")).toBeTruthy();
  });

  it("says what the phase does when nothing is working", () => {
    render(
      <DeploymentHeader progress={0} isDark={false} canRun running={false} version={0} onRun={vi.fn()} />,
    );

    expect(screen.getByText(/Dependency updates assessed by three signals/)).toBeTruthy();
  });
});

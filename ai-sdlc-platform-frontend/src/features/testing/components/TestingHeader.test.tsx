import { afterEach, describe, expect, it, vi } from "vitest";
import { act, cleanup, fireEvent, render, screen } from "@testing-library/react";
import { TestingHeader } from "./TestingHeader";

afterEach(() => {
  cleanup();
  vi.useRealTimers();
});

/**
 * The one way to run the phase again, offered only where it can work.
 *
 * It showed on the loading and error screens, where it could do nothing; it
 * was refused while a review waited and nothing said why; and a long run
 * said "Running" with no sense of how long it had been going.
 */
/**
 * Code Generation's first run starts from its header ("Generate code"), and
 * this phase's started from a button at the foot of the not-started card, out
 * of sight below the six steps it describes.
 */
describe("the first run's button", () => {
  it("is the header's main action before any run", () => {
    const onStart = vi.fn();
    render(<TestingHeader progress={0} isDark={false} running={false} onStart={onStart} />);

    screen.getByRole("button", { name: "Run tests" }).click();

    expect(onStart).toHaveBeenCalledOnce();
    expect(screen.queryByRole("button", { name: /run tests again/i })).toBeNull();
  });

  it("stays busy until the server answers, so a second click sends nothing", async () => {
    let answer!: () => void;
    const onStart = vi.fn(() => new Promise<void>((resolve) => (answer = resolve)));
    render(<TestingHeader progress={0} isDark={false} running={false} onStart={onStart} />);
    const button = screen.getByRole("button", { name: "Run tests" }) as HTMLButtonElement;

    fireEvent.click(button);
    fireEvent.click(button);

    expect(onStart).toHaveBeenCalledOnce();
    expect(button.getAttribute("aria-busy")).toBe("true");
    await act(async () => answer());
    expect(button.getAttribute("aria-busy")).toBeNull();
  });
});

describe("the run tests again button", () => {
  it("is not offered where running again means nothing", () => {
    render(<TestingHeader progress={0} isDark={false} running={false} />);

    expect(screen.queryByRole("button", { name: /run tests again/i })).toBeNull();
  });

  it("is held while a review waits, and says why", () => {
    const onRerun = vi.fn();
    render(
      <TestingHeader
        progress={60}
        isDark={false}
        running={false}
        onRerun={onRerun}
        rerunBlocked="A review is waiting on this run: decide it first, or request changes."
      />,
    );

    const button = screen.getByRole("button", { name: /run tests again/i }) as HTMLButtonElement;
    expect(button.disabled).toBe(true);
    expect(screen.getByText(/A review is waiting on this run/)).toBeTruthy();
    expect(button.getAttribute("aria-describedby")).toBe("rerun-blocked");
  });

  it("stays busy until the server answers, so a second click sends nothing", async () => {
    let answer!: () => void;
    const onRerun = vi.fn(() => new Promise<void>((resolve) => (answer = resolve)));
    render(<TestingHeader progress={100} isDark={false} running={false} onRerun={onRerun} />);
    const button = screen.getByRole("button", { name: /run tests again/i }) as HTMLButtonElement;

    fireEvent.click(button);
    fireEvent.click(button);

    expect(onRerun).toHaveBeenCalledOnce();
    expect(button.getAttribute("aria-busy")).toBe("true");
    await act(async () => answer());
    expect(button.getAttribute("aria-busy")).toBeNull();
  });

  // Every stage of a run showed a spinner at once, and on the live run Test
  // Generation waited three minutes on the model with nothing to say so.
  it("names the stage the run is working on, and for how long", () => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date("2026-10-06T05:23:00Z"));
    render(
      <TestingHeader
        progress={10}
        isDark={false}
        running
        onRerun={vi.fn()}
        runningSince="2026-10-06T05:20:18Z"
        working={{ label: "Test Generation", since: "2026-10-06T05:20:18Z" }}
      />,
    );

    expect(screen.getByText("Working on Test Generation, 2m 42s so far")).toBeTruthy();
    act(() => {
      vi.advanceTimersByTime(2000);
    });
    expect(screen.getByText("Working on Test Generation, 2m 44s so far")).toBeTruthy();
  });

  it("names the stage without a time when the run does not say when it began", () => {
    render(
      <TestingHeader
        progress={10}
        isDark={false}
        running={false}
        working={{ label: "Test Quality", since: null }}
      />,
    );

    expect(screen.getByText("Working on Test Quality")).toBeTruthy();
  });

  it("counts how long a run has been going", () => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date("2026-10-04T10:02:14Z"));
    render(
      <TestingHeader
        progress={30}
        isDark={false}
        running
        onRerun={vi.fn()}
        runningSince="2026-10-04T10:00:00Z"
      />,
    );

    expect(screen.getByRole("button", { name: /running for 2m 14s/i })).toBeTruthy();
    act(() => {
      vi.advanceTimersByTime(3000);
    });
    expect(screen.getByRole("button", { name: /running for 2m 17s/i })).toBeTruthy();
  });

  it("says only that it runs when the start is unknown", () => {
    render(<TestingHeader progress={30} isDark={false} running onRerun={vi.fn()} />);

    expect(screen.getByRole("button", { name: /running…/i })).toBeTruthy();
  });
});

/**
 * Measured on a 1366 laptop: the block holding the selector and the run button
 * was 808 pixels wide in a 650 pixel column, and the progress bar and the
 * button were cut off at the edge. The sentence saying why a run is held sat
 * in the controls' wrapping row, and a wrapping row is as wide as everything
 * in it on one line when its width is asked for.
 */
describe("why a run is held, beside the run button", () => {
  it("sits under the controls, not in their row", () => {
    const { container } = render(
      <TestingHeader
        progress={60}
        isDark={false}
        running={false}
        onRerun={vi.fn()}
        rerunBlocked="A review is waiting on this run: decide it first, or request changes."
      />,
    );

    const controls = container.querySelector("[data-run-controls]") as HTMLElement;
    const reason = screen.getByText(/A review is waiting on this run/);
    expect(controls.contains(screen.getByRole("button", { name: /run tests again/i }))).toBe(true);
    expect(controls.contains(reason)).toBe(false);
    // And it cannot run to one long line of its own.
    expect(reason.className.split(/\s+/).some((one) => one.startsWith("max-w-"))).toBe(true);
  });
});

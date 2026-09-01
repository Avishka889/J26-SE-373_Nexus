import { afterEach, describe, expect, it, vi } from "vitest";
import { act, cleanup, fireEvent, render, screen } from "@testing-library/react";
import { RunStoppedNotice } from "./RunStoppedNotice";

afterEach(cleanup);

/**
 * A run that stopped short of its review left a page of stages waiting for
 * the one before them and a review that never came, with the reason only in
 * Activity. The notice says it stopped, why, and offers the way on.
 */
describe("a run that stopped", () => {
  it("says why, in the server's words", () => {
    render(
      <RunStoppedNotice
        error="server closed the connection unexpectedly"
        startedAt="2026-10-03T09:12:00Z"
        onStartOver={vi.fn()}
        startOverHint="Starting over runs every stage again."
      />,
    );

    expect(screen.getByText(/server closed the connection unexpectedly/i)).toBeTruthy();
    // In the reader's zone (the tests run in Colombo's), not the server's UTC.
    expect(screen.getByText(/It started at 2026-10-03 14:42\./)).toBeTruthy();
  });

  it("starts over once, and is offered again only after the answer", async () => {
    let answer: (value: unknown) => void = () => {};
    const onStartOver = vi.fn(() => new Promise((resolve) => (answer = resolve)));
    render(
      <RunStoppedNotice
        error="it broke"
        startedAt="2026-10-03 09:12"
        onStartOver={onStartOver}
        startOverHint="Starting over runs every stage again."
      />,
    );
    const button = screen.getByRole("button", { name: /start over/i }) as HTMLButtonElement;

    fireEvent.click(button);
    fireEvent.click(button);

    expect(onStartOver).toHaveBeenCalledTimes(1);
    expect(button.disabled).toBe(true);
    await act(async () => answer(undefined));
    expect(button.disabled).toBe(false);
  });
});

/**
 * Starting over generated every stage again and paid again for each one that
 * had finished. Continuing goes on from the stage that stopped the run.
 */
describe("going on with a stopped run", () => {
  it("is offered first, from the stage that stopped it", () => {
    const onContinue = vi.fn();
    render(
      <RunStoppedNotice
        error="it broke"
        startedAt="2026-10-03 09:12"
        onContinue={onContinue}
        stoppedAtLabel="Architecture Graph"
        onStartOver={vi.fn()}
        startOverHint="Starting over runs every stage again."
      />,
    );

    fireEvent.click(screen.getByRole("button", { name: "Continue from Architecture Graph" }));

    expect(onContinue).toHaveBeenCalledTimes(1);
    expect(screen.getByRole("button", { name: /start over/i })).toBeTruthy();
  });
});

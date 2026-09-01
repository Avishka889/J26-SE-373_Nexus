import { afterEach, describe, expect, it, vi } from "vitest";
import { act, cleanup, fireEvent, render, screen } from "@testing-library/react";
import { Button } from "./primitives";

/**
 * A second click on work already in flight.
 *
 * Every action here goes to a server that takes a moment, and the button that
 * started it stays on screen until the answer arrives. Reported from the
 * browser: clicking Generate twice sent two requests, and the second came back
 * as an error about a run already being in flight, which reads as the reader's
 * mistake when it was the page's.
 */
afterEach(cleanup);

describe("a busy button", () => {
  it("cannot be clicked again", () => {
    const onClick = vi.fn();
    render(
      <Button busy onClick={onClick}>
        Generate
      </Button>,
    );
    const button = screen.getByRole("button", { name: /generate/i });
    fireEvent.click(button);
    expect(onClick).not.toHaveBeenCalled();
    expect((button as HTMLButtonElement).disabled).toBe(true);
  });

  it("says so, so the disabling does not read as a broken control", () => {
    render(<Button busy>Generate</Button>);
    expect(screen.getByRole("button").getAttribute("aria-busy")).toBe("true");
  });

  it("works normally when it is not busy", () => {
    const onClick = vi.fn();
    render(<Button onClick={onClick}>Generate</Button>);
    fireEvent.click(screen.getByRole("button", { name: /generate/i }));
    expect(onClick).toHaveBeenCalledTimes(1);
  });

  it("stays disabled when disabled for its own reasons", () => {
    const onClick = vi.fn();
    render(
      <Button disabled onClick={onClick}>
        Approve
      </Button>,
    );
    fireEvent.click(screen.getByRole("button", { name: /approve/i }));
    expect(onClick).not.toHaveBeenCalled();
  });
});

/**
 * A click whose request is still in flight.
 *
 * Only some buttons were given `busy`, so Run tests stayed clickable, with
 * nothing on it, until the server answered: reported from the live run, where a
 * click seemed to do nothing. A handler that returns its request now keeps the
 * button busy until the request settles, without a flag per button.
 */
describe("a click whose request is in flight", () => {
  function deferred() {
    let settle!: { resolve: () => void; reject: (error: Error) => void };
    const promise = new Promise<void>((resolve, reject) => {
      settle = { resolve, reject };
    });
    return { promise, ...settle };
  }

  it("keeps the button busy until the request is answered, and a second click sends nothing", async () => {
    const request = deferred();
    const onClick = vi.fn(() => request.promise);
    render(<Button onClick={onClick}>Run tests</Button>);
    const button = screen.getByRole("button", { name: /run tests/i }) as HTMLButtonElement;

    fireEvent.click(button);
    fireEvent.click(button);

    expect(onClick).toHaveBeenCalledTimes(1);
    expect(button.disabled).toBe(true);
    expect(button.getAttribute("aria-busy")).toBe("true");

    await act(async () => request.resolve());
    expect(button.disabled).toBe(false);
    expect(button.getAttribute("aria-busy")).toBeNull();
  });

  it("sends nothing for a second click in the same frame, before the button redraws", async () => {
    const request = deferred();
    const onClick = vi.fn(() => request.promise);
    render(<Button onClick={onClick}>Run tests</Button>);
    const button = screen.getByRole("button", { name: /run tests/i });

    // One act, so the second click lands before React redraws the button as disabled.
    act(() => {
      button.click();
      button.click();
    });

    expect(onClick).toHaveBeenCalledTimes(1);
    await act(async () => request.resolve());
  });

  it("frees the button when the request is refused too", async () => {
    const request = deferred();
    render(<Button onClick={() => request.promise}>Run the app</Button>);
    const button = screen.getByRole("button", { name: /run the app/i }) as HTMLButtonElement;

    fireEvent.click(button);
    expect(button.disabled).toBe(true);

    await act(async () => request.reject(new Error("refused")));
    expect(button.disabled).toBe(false);
  });

  it("leaves a handler that returns nothing as it was", () => {
    const onClick = vi.fn();
    render(<Button onClick={onClick}>Open</Button>);
    const button = screen.getByRole("button", { name: /open/i }) as HTMLButtonElement;

    fireEvent.click(button);
    fireEvent.click(button);

    expect(onClick).toHaveBeenCalledTimes(2);
    expect(button.disabled).toBe(false);
  });
});

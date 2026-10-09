import { afterEach, describe, expect, it, vi } from "vitest";
import { act, cleanup, fireEvent, render, screen } from "@testing-library/react";
import { useUiStore } from "@/store/ui";
import { useDebouncedText } from "./useDebouncedText";

/**
 * Typing eight characters must save once, with all eight.
 *
 * Wired straight to the mutation, the organisation field sent one PATCH per
 * keystroke: seventeen requests in two and a half seconds in one real session,
 * racing each other over a single row, so "vinozhan" was stored as "vinoz".
 */
afterEach(cleanup);

function Field({
  value,
  save,
}: {
  value: string;
  save: (next: string) => void | Promise<unknown>;
}) {
  const [text, setText] = useDebouncedText(value, save, 100);
  return (
    <input aria-label="org" value={text} onChange={(e) => setText(e.target.value)} />
  );
}

function type(input: HTMLInputElement, text: string) {
  // `fireEvent.change` rather than a raw dispatch: React tracks the value
  // setter, so an input event it did not cause never reaches onChange.
  for (let i = 1; i <= text.length; i += 1) {
    fireEvent.change(input, { target: { value: text.slice(0, i) } });
  }
}

describe("a field that saves when the typing stops", () => {
  it("saves once, with everything that was typed", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    const save = vi.fn();
    render(<Field value="" save={save} />);
    const input = screen.getByLabelText("org") as HTMLInputElement;

    type(input, "vinozhan");
    expect(save).not.toHaveBeenCalled();

    await act(async () => {
      vi.advanceTimersByTime(150);
    });

    expect(save).toHaveBeenCalledTimes(1);
    expect(save).toHaveBeenCalledWith("vinozhan");
    vi.useRealTimers();
  });

  it("shows what is being typed rather than the server's copy", async () => {
    /** A refetch landing mid word must not rewrite the field under the cursor. */
    vi.useFakeTimers({ shouldAdvanceTime: true });
    const save = vi.fn();
    const view = render(<Field value="" save={save} />);
    const input = screen.getByLabelText("org") as HTMLInputElement;

    type(input, "vin");
    view.rerender(<Field value="something-else" save={save} />);

    expect(input.value).toBe("vin");
    vi.useRealTimers();
  });

  it("keeps showing what was typed while its save is on its way", async () => {
    /** The field emptied the moment it sent the save and showed the server's old
     * copy until the answer came, which on the Atlas tab read as the field clearing
     * itself, or for good when that answer was lost. */
    vi.useFakeTimers({ shouldAdvanceTime: true });
    let answer: () => void = () => {};
    const save = vi.fn(() => new Promise<void>((resolve) => (answer = resolve)));
    const view = render(<Field value="" save={save} />);
    const input = screen.getByLabelText("org") as HTMLInputElement;

    type(input, "Cluster0");
    await act(async () => {
      vi.advanceTimersByTime(150);
    });

    expect(save).toHaveBeenCalledWith("Cluster0");
    expect(input.value).toBe("Cluster0");
    // The answer lands, and the server's copy, now the same, takes over.
    view.rerender(<Field value="Cluster0" save={save} />);
    await act(async () => {
      answer();
    });
    expect(input.value).toBe("Cluster0");
    view.rerender(<Field value="from elsewhere" save={save} />);
    expect(input.value).toBe("from elsewhere");
    vi.useRealTimers();
  });

  it("adopts a new value from elsewhere while nobody is typing", async () => {
    const save = vi.fn();
    const view = render(<Field value="one" save={save} />);
    const input = screen.getByLabelText("org") as HTMLInputElement;
    expect(input.value).toBe("one");

    view.rerender(<Field value="two" save={save} />);
    expect(input.value).toBe("two");
  });
});

/**
 * An edit typed just before leaving the tab was dropped: the timer was cleared
 * when the field unmounted, and nothing sent what it held. A refused save said
 * nothing either, so a reader left believing the field was stored.
 */
describe("what a field does with an edit it holds", () => {
  it("saves it when the field goes away before the typing pause", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    const save = vi.fn();
    const view = render(<Field value="" save={save} />);
    type(screen.getByLabelText("org") as HTMLInputElement, "Ada");

    view.unmount();

    expect(save).toHaveBeenCalledWith("Ada");
    vi.useRealTimers();
  });

  it("says so when the server refuses it", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    useUiStore.setState({ toasts: [] });
    const save = vi.fn(() => Promise.reject(new Error("Cannot reach the server.")));
    render(<Field value="" save={save} />);
    type(screen.getByLabelText("org") as HTMLInputElement, "Ada");

    await act(async () => {
      vi.advanceTimersByTime(150);
    });

    const toasts = useUiStore.getState().toasts;
    expect(toasts.some((one) => one.type === "error" && /not saved/i.test(one.title))).toBe(true);
    vi.useRealTimers();
  });
});

/**
 * Saving the Atlas secret within a second of typing an identifier checked
 * the identifier the server still held: the edit was waiting for its pause.
 */
describe("an edit sent before its pause", () => {
  it("goes at once when asked, and the answer can be waited for", async () => {
    function Flushable({ save }: { save: (next: string) => Promise<unknown> }) {
      const [text, setText, send] = useDebouncedText("", save, 10_000);
      return (
        <>
          <input aria-label="org" value={text} onChange={(e) => setText(e.target.value)} />
          <button type="button" onClick={() => void send()}>
            Send now
          </button>
        </>
      );
    }
    const save = vi.fn(async () => undefined);
    render(<Flushable save={save} />);
    type(screen.getByLabelText("org") as HTMLInputElement, "Cluster1");

    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: "Send now" }));
    });

    expect(save).toHaveBeenCalledTimes(1);
    expect(save).toHaveBeenCalledWith("Cluster1");
  });
});

import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { DecisionBar } from "./DecisionBar";

afterEach(cleanup);

function bar(onRequestChanges: (note: string) => void | Promise<unknown>) {
  render(
    <DecisionBar
      headline="This phase is waiting on you"
      detail="Code version 3"
      approveLabel="Approve code"
      notePrompt="What needs to change"
      notePlaceholder="Say what is wrong"
      onApprove={vi.fn()}
      onRequestChanges={onRequestChanges}
    />,
  );
  fireEvent.click(screen.getByRole("button", { name: /Request changes/ }));
  const note = screen.getByLabelText("What needs to change") as HTMLTextAreaElement;
  fireEvent.change(note, { target: { value: "Split the order endpoints." } });
  fireEvent.click(screen.getByRole("button", { name: "Send the note" }));
  return note;
}

/**
 * A change note is the reviewer's reasoning, so a refused one is kept.
 *
 * The note used to be cleared and its box closed before the request answered;
 * a refusal threw the reasoning away with no way to get it back.
 */
describe("the decision note", () => {
  it("stays open with its text when the request is refused", async () => {
    const onRequestChanges = vi.fn(() => Promise.reject(new Error("No review is waiting")));
    bar(onRequestChanges);

    await waitFor(() => expect(onRequestChanges).toHaveBeenCalledWith("Split the order endpoints."));
    await Promise.resolve();
    expect((screen.getByLabelText("What needs to change") as HTMLTextAreaElement).value).toBe(
      "Split the order endpoints.",
    );
  });

  it("closes once the request is accepted", async () => {
    bar(vi.fn(() => Promise.resolve()));

    await waitFor(() => expect(screen.queryByLabelText("What needs to change")).toBeNull());
  });
});

/**
 * Approving was one click whatever had failed: a code version was approved
 * with its typecheck failing, and the line saying so was cut off on a phone.
 * What is outstanding now comes first, and approving over it needs a reason.
 */
describe("approving over what is outstanding", () => {
  const withConcerns = (onApprove: (note?: string) => void | Promise<unknown>, concerns: string[]) =>
    render(
      <DecisionBar
        headline="This phase is waiting on you"
        detail="Code version 3"
        concerns={concerns}
        approveLabel="Approve code"
        notePrompt="What needs to change"
        notePlaceholder="Say what is wrong"
        onApprove={onApprove}
        onRequestChanges={vi.fn()}
      />,
    );

  it("says what is outstanding and asks why before approving", async () => {
    const onApprove = vi.fn(() => Promise.resolve());
    withConcerns(onApprove, ["the build did not pass"]);

    expect(screen.getByText("Outstanding: the build did not pass")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: /Approve code/ }));
    expect(onApprove).not.toHaveBeenCalled();

    const anyway = screen.getByRole("button", { name: "Approve anyway" }) as HTMLButtonElement;
    expect(anyway.disabled).toBe(true);
    fireEvent.change(screen.getByLabelText("Why approve with this outstanding"), {
      target: { value: "The typecheck failure is in a test helper we are replacing." },
    });
    fireEvent.click(anyway);

    await waitFor(() =>
      expect(onApprove).toHaveBeenCalledWith("The typecheck failure is in a test helper we are replacing."),
    );
  });

  it("approves in one click when nothing is outstanding", () => {
    const onApprove = vi.fn();
    withConcerns(onApprove, []);

    fireEvent.click(screen.getByRole("button", { name: /Approve code/ }));

    expect(onApprove).toHaveBeenCalledWith();
    expect(screen.queryByLabelText("Why approve with this outstanding")).toBeNull();
  });
});

/**
 * A review the phase has moved past: changes there would regenerate from what
 * is no longer current, so the bar turns them off and says what to do instead.
 */
describe("requesting changes that would not help", () => {
  it("is off, and the bar says what to do instead", () => {
    const onRequestChanges = vi.fn();
    render(
      <DecisionBar
        headline="This phase is waiting on you"
        detail="Code version 3"
        approveLabel="Approve code"
        notePrompt="What needs to change"
        notePlaceholder="Say what is wrong"
        onApprove={vi.fn()}
        onRequestChanges={onRequestChanges}
        changesDisabledReason="Generate again to regenerate from design version 2."
      />,
    );

    const request = screen.getByRole("button", { name: /Request changes/ }) as HTMLButtonElement;
    expect(request.disabled).toBe(true);
    expect(screen.getByText("Generate again to regenerate from design version 2.")).toBeTruthy();
    fireEvent.click(request);
    expect(screen.queryByLabelText("What needs to change")).toBeNull();
    expect(onRequestChanges).not.toHaveBeenCalled();
  });
});

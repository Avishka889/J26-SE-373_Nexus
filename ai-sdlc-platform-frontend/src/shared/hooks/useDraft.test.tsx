import { afterEach, describe, expect, it } from "vitest";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { useDraft } from "./useDraft";

afterEach(cleanup);

function Box({ draftKey }: { draftKey: string }) {
  const [text, setText] = useDraft(draftKey);
  return <textarea aria-label="note" value={text} onChange={(event) => setText(event.target.value)} />;
}

function box() {
  return screen.getByLabelText("note") as HTMLTextAreaElement;
}

/**
 * A note survives its box going away.
 *
 * Deployment renders only the open stage, and every decision note lived in its
 * stage's own state: a reviewer halfway through a High update's note who
 * opened Risk Assessment to check the evidence came back to an empty box.
 */
describe("a draft", () => {
  it("is still there when its box unmounts and comes back", () => {
    const { unmount } = render(<Box draftKey="p_1:update:u-1" />);
    fireEvent.change(box(), { target: { value: "Check the changelog first." } });
    unmount();

    render(<Box draftKey="p_1:update:u-1" />);

    expect(box().value).toBe("Check the changelog first.");
  });

  it("belongs to its own key, and an emptied draft is gone", () => {
    const { unmount } = render(<Box draftKey="p_1:update:u-2" />);
    fireEvent.change(box(), { target: { value: "Only this update." } });
    unmount();

    const other = render(<Box draftKey="p_2:update:u-2" />);
    expect(box().value).toBe("");
    other.unmount();

    render(<Box draftKey="p_1:update:u-2" />);
    fireEvent.change(box(), { target: { value: "" } });
    cleanup();
    render(<Box draftKey="p_1:update:u-2" />);
    expect(box().value).toBe("");
  });
});

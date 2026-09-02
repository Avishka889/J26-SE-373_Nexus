import { act, renderHook, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import type { Attachment } from "@/types/document";
import { extractDocument } from "./api";
import { useAttachments } from "./hooks";

/**
 * The window between picking a file and having its text.
 *
 * The read is mocked so that window can be held open and asserted on. It is a
 * real window in the product too: a PDF goes to the orchestrator with a sixty
 * second timeout, and Enter submits.
 */
vi.mock("./api", () => ({ extractDocument: vi.fn() }));

const read = vi.mocked(extractDocument);

const EXTRACTED: Omit<Attachment, "id"> = {
  name: "brief.md",
  format: "md",
  bytes: 7,
  pages: null,
  pagesWithoutText: null,
  words: 2,
  chars: 7,
  charsAvailable: 7,
  truncated: false,
  text: "# Brief",
};

function pick(name = "brief.md"): File {
  return new File(["# Brief"], name, { type: "text/markdown" });
}

beforeEach(() => {
  read.mockReset();
});

describe("useAttachments", () => {
  it("counts a file that is still being read and keeps it out of documents", async () => {
    let finish: (value: Omit<Attachment, "id">) => void = () => {};
    read.mockReturnValueOnce(
      new Promise((resolve) => {
        finish = resolve;
      }),
    );

    const { result } = renderHook(() => useAttachments());
    act(() => result.current.add([pick()]));

    expect(result.current.slots).toHaveLength(1);
    expect(result.current.slots[0].state).toBe("reading");
    // A composer submits `documents`, so a file in this state contributes
    // nothing to what is sent. `readingCount` is what says so out loud: without
    // it a submit at this instant sent the typed text alone, started the run,
    // and unmounted the composer with the read still in flight, which is this
    // feature's original bug with a timer on it.
    expect(result.current.documents).toEqual([]);
    expect(result.current.readingCount).toBe(1);

    await act(async () => {
      finish(EXTRACTED);
    });

    await waitFor(() => expect(result.current.readingCount).toBe(0));
    expect(result.current.documents).toHaveLength(1);
    expect(result.current.documents[0].text).toBe("# Brief");
  });

  it("stops counting a file that was refused", async () => {
    read.mockRejectedValueOnce(new Error("Cannot read .xlsx files."));

    const { result } = renderHook(() => useAttachments());
    act(() => result.current.add([pick("budget.xlsx")]));

    await waitFor(() => expect(result.current.slots[0].state).toBe("failed"));
    // A refusal is a finished read. Counting it as still reading would leave the
    // composer blocked with no way out but removing a chip.
    expect(result.current.readingCount).toBe(0);
  });

  it("stops counting a file that was removed mid read", async () => {
    read.mockReturnValueOnce(new Promise(() => {}));

    const { result } = renderHook(() => useAttachments());
    act(() => result.current.add([pick()]));
    expect(result.current.readingCount).toBe(1);

    act(() => result.current.remove(result.current.slots[0].id));
    expect(result.current.readingCount).toBe(0);
  });
});

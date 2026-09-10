import { describe, expect, it } from "vitest";
import type { DesignSnapshot } from "../api/types";
import { composerHelper, composerSends, queuedLine } from "./composer";

function snapshot(reviewWaits: boolean, queuedChanges: string[] = []): DesignSnapshot {
  return {
    requirementsVersion: 1,
    stages: { "design-review": { status: reviewWaits ? "complete" : "pending" } },
    gate: { decision: null, history: [] },
    queuedChanges,
  } as unknown as DesignSnapshot;
}

/**
 * The chat does what it says.
 *
 * At a pending review a chat message was stored as a note that waited for the
 * decision, while the toast said the design was regenerating; approving then
 * regenerated it unannounced, at a version that needed approving again.
 */
describe("a message sent from the chat", () => {
  it("requests changes when a review waits, and says so", () => {
    expect(composerSends(snapshot(true))).toBe("request-changes");
    expect(composerHelper(snapshot(true))).toBe(
      "Version 1 waits on your review. Sending requests changes at it, and the design regenerates.",
    );
  });

  it("is a change note otherwise, and the whole design regenerates", () => {
    expect(composerSends(snapshot(false))).toBe("change-note");
    expect(composerHelper(snapshot(false))).toBe(
      "Version 1. Sending regenerates the design, Requirements Analysis included.",
    );
  });
});

describe("a message sent while the design waits on its questions", () => {
  it("says it is read with the answers, rather than that the design regenerates", () => {
    const paused = { ...snapshot(false), questionsPending: true } as DesignSnapshot;

    expect(composerHelper(paused)).toBe(
      "Version 1 waits on its questions. A note sent now is read with your answers when you continue with them.",
    );
  });
});

describe("changes waiting on the review", () => {
  it("are named, with what approving will do", () => {
    expect(queuedLine(snapshot(true, ["add a genre field"]))).toBe(
      "1 change waits on this decision: approving starts version 2 with it",
    );
    expect(queuedLine(snapshot(true, ["a", "b"]))).toBe(
      "2 changes wait on this decision: approving starts version 2 with them",
    );
  });

  it("say nothing when there are none", () => {
    expect(queuedLine(snapshot(true))).toBeNull();
  });
});

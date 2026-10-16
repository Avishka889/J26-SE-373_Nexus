import { describe, expect, it, vi } from "vitest";
import { buildTestingConversation } from "./conversation";
import { buildTestSnapshot } from "../fixtures/buildTestSnapshot";
import type { TestSnapshot } from "../api/types";

/**
 * The transcript this phase had nowhere to show until it got a conversation.
 *
 * It matters more here than the missing panel suggests. C3 writes its refusals
 * to the thread: when it will not subtract two passes that were not measured
 * alike, the reason goes there and nothing is stored, so a phase with no
 * transcript had the one sentence explaining an absent re-verification recorded
 * and unreadable.
 */
function withThread(entries: TestSnapshot["thread"]): TestSnapshot {
  return { ...buildTestSnapshot("p1", "approved", 1), thread: entries } as TestSnapshot;
}

describe("the testing conversation", () => {
  it("shows a refusal the server wrote to the thread", () => {
    const snapshot = withThread([
      {
        id: "m1",
        kind: "system",
        stageId: "remediation",
        author: "Testing and Security",
        content: "the two passes cannot be compared: the arms differ",
        at: "2026-09-26T10:00:00Z",
        producedVersion: null,
      },
    ]);

    const [message] = buildTestingConversation({ snapshot, onOpenStage: vi.fn() });

    expect(message.role).toBe("system");
    expect(message.content).toContain("cannot be compared");
  });

  it("opens the stage a message belongs to", () => {
    const onOpenStage = vi.fn();
    const snapshot = withThread([
      {
        id: "m1",
        kind: "stage_summary",
        stageId: "self-healing",
        author: "Testing and Security",
        content: "1 healed, 1 refused",
        at: "2026-09-26T10:00:00Z",
        producedVersion: null,
      },
    ]);

    const [message] = buildTestingConversation({ snapshot, onOpenStage });
    message.onOpen?.();

    expect(onOpenStage).toHaveBeenCalledWith("self-healing");
    expect(message.chip).toBe("Self Healing");
    // The role is the only thing that separates a stage summary from any other
    // message carrying a stage id: both get a chip and both open the stage.
    // Asserting those two alone passed with the branch removed entirely.
    expect(message.role).toBe("agent");
  });

  it("says which version a message produced", () => {
    // "Why is this at version 3" is the question a transcript exists to answer.
    const snapshot = withThread([
      {
        id: "m1",
        kind: "user_note",
        stageId: null,
        author: "you",
        content: "round the totals",
        at: "2026-09-26T10:00:00Z",
        producedVersion: 3,
      },
    ]);

    const [message] = buildTestingConversation({ snapshot, onOpenStage: vi.fn() });

    expect(message.chip).toContain("v3");
  });

  it("is empty when the phase has said nothing, rather than inventing a line", () => {
    expect(buildTestingConversation({ snapshot: withThread([]), onOpenStage: vi.fn() })).toEqual([]);
  });
});

import { beforeEach, describe, expect, it, vi } from "vitest";
import { createRequirementsApi } from "../api/createRequirementsApi";
import { buildSnapshot, readDesign, resetDesignDb, writeDesign } from "../fixtures/designDb";
import { nexuspaySeed } from "@/entities/design-seed/projects/nexuspay";
import { buildConversation } from "./conversation";

/**
 * The chat is a transcript of what happened, and the only place prose is written.
 *
 * The phase borrowed the chat mental model at the front door and abandoned it
 * inside, where the conversation was a card at the bottom of one stage. These
 * assertions are about what a transcript has to be: the reader's own words
 * first, every entry a real event, and questions asked and answered in one place
 * so answering clears them everywhere.
 */

const api = createRequirementsApi();
const PROJECT = "p1";
const INPUT = "The system shall allow customers to make payments using credit cards.";

const build = (over: Parameters<typeof buildConversation>[0]["snapshot"]) =>
  buildConversation({
    snapshot: over,
    onOpenStage: () => {},
    onAnswerQuestion: () => {},
    answering: false,
  });

beforeEach(() => {
  resetDesignDb();
  writeDesign(PROJECT, buildSnapshot(PROJECT, nexuspaySeed, "awaiting", INPUT));
});

describe("the transcript", () => {
  it("opens with the reader's own input, verbatim", () => {
    const messages = build(readDesign(PROJECT));
    expect(messages[0].role).toBe("user");
    expect(messages[0].content).toBe(INPUT);
    // A pasted document collapses rather than filling the panel.
    expect(messages[0].collapsible).toBe(true);
  });

  it("makes every agent stage summary open its stage", () => {
    const opened: string[] = [];
    const messages = buildConversation({
      snapshot: readDesign(PROJECT),
      onOpenStage: (id) => opened.push(id),
      onAnswerQuestion: () => {},
      answering: false,
    });

    const summaries = messages.filter((m) => m.role === "agent" && m.onOpen);
    expect(summaries.length).toBeGreaterThan(0);
    for (const summary of summaries) {
      expect(summary.openLabel).toMatch(/^Open /);
      summary.onOpen?.();
    }
    expect(opened).toContain("requirements");
    expect(opened).toContain("wireframes");
  });

  it("asks each open question as an agent message with its reply box inside", () => {
    const snapshot = readDesign(PROJECT);
    const open = snapshot.questions.filter((q) => !q.answer);
    expect(open.length).toBeGreaterThan(0);

    const messages = build(snapshot);
    const asked = messages.filter((m) => m.answer);
    expect(asked).toHaveLength(open.length);
    for (const message of asked) {
      expect(message.role).toBe("agent");
      // The affordance is in the bubble, because that is what the question is:
      // the agent waiting for a reply.
      expect(message.answer?.placeholder).toBeTruthy();
    }
  });

  it("stops asking a question once it has been answered", async () => {
    const before = build(readDesign(PROJECT)).filter((m) => m.answer).length;
    await api.answerQuestion(PROJECT, "Q-1", "Hold it for manual review.");

    const after = build(readDesign(PROJECT));
    expect(after.filter((m) => m.answer)).toHaveLength(before - 1);
    // And the answer is now part of the record rather than vanishing.
    expect(after.some((m) => m.role === "user" && m.content.includes("Hold it"))).toBe(true);
  });

  it("puts the version chip on the message that opened it", async () => {
    await api.submitChange(PROJECT, "Add refunds", "A. Chen");
    const messages = build(readDesign(PROJECT));

    const note = messages.find((m) => m.content === "Add refunds");
    expect(note?.chip).toBe("Version 2");

    // And only on that one: an answer sitting between two notes must not pick up
    // a version it did not cause.
    const chips = messages.filter((m) => m.chip?.startsWith("Version"));
    expect(chips.map((m) => m.chip)).toEqual(["Version 1", "Version 2"]);
  });

  it("records a gate decision as a system entry", async () => {
    await api.submitGateDecision(PROJECT, { kind: "approved", by: "A. Chen" });
    const messages = build(readDesign(PROJECT));
    const decision = messages.filter((m) => m.role === "system");
    expect(decision.some((m) => m.content.includes("Approved the design"))).toBe(true);
  });

  it("carries no entry that is not a real event", () => {
    const snapshot = readDesign(PROJECT);
    const messages = build(snapshot);

    const realContent = new Set([
      ...snapshot.thread.map((m) => m.content),
      ...snapshot.thread.flatMap((m) => (m.question ? [m.question.question] : [])),
      ...snapshot.questions.map((q) => q.question),
    ]);
    for (const message of messages) {
      expect(realContent.has(message.content), `invented entry: ${message.content}`).toBe(true);
    }
  });

  it("keeps the requirements list out of the transcript", () => {
    const snapshot = readDesign(PROJECT);
    const messages = build(snapshot);
    // A log is not state. The chat carries the summary that links to the
    // artifact; the artifact itself stays where it can be edited and filtered.
    for (const requirement of snapshot.requirements) {
      expect(messages.some((m) => m.content === requirement.text)).toBe(false);
    }
  });

  it("uses no em or en dash anywhere it speaks", () => {
    for (const message of build(readDesign(PROJECT))) {
      expect(message.content).not.toContain("—");
      expect(message.content).not.toContain("–");
    }
  });
});

describe("an answered question", () => {
  /**
   * Answering one took it out of the transcript, since only open questions were
   * drawn, and left the answer on its own: the reader saw "one user" and nothing
   * saying what it answered. The server now pairs each answer with its question.
   */
  const ANSWER = "Hold it for manual review.";
  const ASKED_AT = "2026-10-06T03:24:05Z";
  const ANSWERED_AT = "2026-10-06T03:34:42Z";

  /**
   * The snapshot as the server answers it: the answer's own words in the thread,
   * paired with the question they answer. Built here rather than through the
   * fixture API, whose answer carries the question inside the reader's words.
   */
  function answered(
    question: { id: string; question: string; traces: string[] },
    { stillAsked }: { stillAsked: boolean },
  ) {
    const snapshot = readDesign(PROJECT);
    return {
      ...snapshot,
      questions: stillAsked
        ? snapshot.questions.map((q) =>
            q.id === question.id ? { ...q, answer: ANSWER, answeredAt: ANSWERED_AT } : q,
          )
        : snapshot.questions,
      thread: [
        ...snapshot.thread,
        {
          id: "t-answer",
          kind: "answer" as const,
          stageId: "requirements" as const,
          author: "A. Chen",
          content: ANSWER,
          at: ANSWERED_AT,
          producedVersion: null,
          question: { ...question, askedAt: ASKED_AT },
        },
      ],
    };
  }

  it("stays in the transcript, asked by the agent right above its answer", () => {
    const asked = readDesign(PROJECT).questions.find((q) => q.id === "Q-1");
    if (!asked) throw new Error("the seed asks Q-1");

    const messages = build(answered(asked, { stillAsked: true }));

    const at = messages.findIndex((m) => m.role === "user" && m.content === ANSWER);
    expect(at).toBeGreaterThan(0);
    const question = messages[at - 1];
    expect(question.role).toBe("agent");
    expect(question.content).toBe(asked.question);
    expect(question.chip).toBe(asked.traces.join(", "));
    expect(question.at).toBe(ASKED_AT);
    // Answered, so nothing waits on the reader any more.
    expect(question.answer).toBeUndefined();
    expect(messages.filter((m) => m.content === asked.question)).toHaveLength(1);
  });

  it("keeps a question from an earlier version, which the snapshot no longer asks", () => {
    const earlier = { id: "Q-1", question: "Who uses the tracker?", traces: ["R-1"] };

    const messages = build(answered(earlier, { stillAsked: false }));

    const at = messages.findIndex((m) => m.role === "user" && m.content === ANSWER);
    expect(messages[at - 1].content).toBe(earlier.question);
  });
});

describe("a project that has not run yet", () => {
  it("has an empty transcript rather than an invented one", () => {
    vi.useRealTimers();
    const empty = buildSnapshot("blank", nexuspaySeed, "empty");
    expect(build(empty)).toHaveLength(0);
  });
});

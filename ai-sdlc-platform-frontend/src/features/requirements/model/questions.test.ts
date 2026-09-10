import { describe, expect, it } from "vitest";
import { questionsLine } from "./questions";

describe("the header while the design waits on its questions", () => {
  it("counts the questions still open", () => {
    expect(questionsLine(3)).toBe("Waiting for your answers to 3 questions");
    expect(questionsLine(1)).toBe("Waiting for your answers to one question");
  });

  it("says what to do once every one is answered", () => {
    expect(questionsLine(0)).toBe("Every question is answered: continue with your answers");
  });
});

import { describe, expect, it } from "vitest";
import { transcriptOf } from "./transcript";

describe("the console comes from the steps that ran", () => {
  it("each step contributes its command and its outcome", () => {
    const lines = transcriptOf([
      { name: "install", command: "npm ci", outcome: "passed", logTail: "ok" },
    ]);

    expect(lines.map((one) => one.kind)).toEqual(["cmd", "info", "pass"]);
    expect(lines[0].text).toBe("npm ci");
  });

  it("a step that never ran says so rather than looking clean", () => {
    const lines = transcriptOf([
      { name: "vitest", command: "vitest run", outcome: "not-run", logTail: "" },
    ]);

    expect(lines[1].kind).toBe("muted");
    expect(lines[1].text).toContain("not run");
  });

  it("a failing step is marked as failing", () => {
    const lines = transcriptOf([
      { name: "vitest", command: "vitest run", outcome: "failed", logTail: "" },
    ]);

    expect(lines[lines.length - 1].kind).toBe("fail");
  });

  it("a step that hit its time cap is a failure, and says which", () => {
    const lines = transcriptOf([
      { name: "build", command: "npm run build", outcome: "timed-out", logTail: null },
    ]);

    expect(lines[lines.length - 1]).toEqual({ kind: "fail", text: "build timed out" });
  });
});

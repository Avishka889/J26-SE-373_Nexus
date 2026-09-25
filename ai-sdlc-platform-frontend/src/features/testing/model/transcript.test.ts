import { describe, expect, it } from "vitest";
import type { ConsoleLine } from "@/shared/ui/console";
import { readableTranscript } from "./transcript";

const info = (text: string): ConsoleLine => ({ kind: "info", text });

const LIVE: ConsoleLine[] = [
  { kind: "cmd", text: "npm install --no-audit --no-fund" },
  info("{"),
  info("npm warn EBADENGINE   package: '@babel/plugin-syntax-jsx@8.0.1',"),
  info("npm warn EBADENGINE   required: { node: '^22.18.0 || >=24.11.0' },"),
  info("npm warn EBADENGINE   current: { node: 'v22.17.0', npm: '10.9.2' }"),
  info("npm warn EBADENGINE }"),
  { kind: "pass", text: "install passed" },
  { kind: "cmd", text: "npx vitest run --reporter=json" },
  info("JSON report written to /tmp/c3-workspaces/p_a97a9c995e9b/v1/apps/api/.c3/vitest.json"),
  { kind: "fail", text: "tests (apps/api) failed" },
];

/**
 * The live run's transcript: over a hundred lines of npm's engine warnings in a
 * small box, and the two lines that said which tests failed under them.
 */
describe("a run's transcript, as it is read", () => {
  it("folds a run of npm warnings to one line that says how many", () => {
    const { lines, folded } = readableTranscript(LIVE);

    expect(folded).toBe(5);
    expect(lines.map((one) => one.text)).toEqual([
      "npm install --no-audit --no-fund",
      "5 lines of npm warnings folded",
      "install passed",
      "npx vitest run --reporter=json",
      "JSON report written to apps/api/.c3/vitest.json",
      "tests (apps/api) failed",
    ]);
    expect(lines[1].kind).toBe("muted");
  });

  it("shows every line as recorded when asked", () => {
    const { lines, folded } = readableTranscript(LIVE, { all: true });

    expect(folded).toBe(0);
    expect(lines).toHaveLength(LIVE.length);
    expect(lines[2].text).toContain("EBADENGINE");
  });

  it("leaves a warning or two where they are", () => {
    const few: ConsoleLine[] = [info("npm warn deprecated inflight@1.0.6"), info("added 12 packages")];

    expect(readableTranscript(few)).toEqual({ lines: few, folded: 0 });
  });

  it("names a file by where it is in the repository, not on the machine that ran it", () => {
    const { lines } = readableTranscript(LIVE, { all: true });

    expect(lines.some((one) => one.text.includes("/tmp/c3-workspaces"))).toBe(false);
    expect(lines.find((one) => one.text.startsWith("JSON report"))!.text).toBe(
      "JSON report written to apps/api/.c3/vitest.json",
    );
  });

  it("folds nothing that is not a warning, however long the log", () => {
    const log = Array.from({ length: 8 }, (_, i) => info(`compiled module ${i}`));

    expect(readableTranscript(log).folded).toBe(0);
  });
});

import type { ConsoleLine } from "@/shared/ui/console";

/** Where a run's files live on the machine that ran it, which the reader has no use for. */
const WORKSPACE = /\/tmp\/c3-workspaces\/[^/\s]+\/v\d+\//g;

/** A line of npm's warnings, or the brace a cut log left from one. */
const WARNING = /^(npm warn\b|[{}]$)/i;

/** A run of warnings shorter than this is left as it is. */
const FOLD_FROM = 4;

/**
 * A run's transcript as a reader wants it: what ran and what came of it.
 *
 * The live run's transcript opened with over a hundred lines of npm's engine
 * warnings in a box fourteen lines tall, and the two lines that mattered, which
 * app's tests failed, were at the bottom of it. A run of warnings is folded to
 * one line saying how many, and `all` shows every line as recorded.
 *
 * Paths lose the workspace they were run in: `/tmp/.../v1/apps/api/x` reads as
 * `apps/api/x`, which is where the file is in the repository.
 */
export function readableTranscript(
  lines: readonly ConsoleLine[],
  { all = false }: { all?: boolean } = {},
): { lines: ConsoleLine[]; folded: number } {
  const shown: ConsoleLine[] = [];
  let folded = 0;
  let run: ConsoleLine[] = [];
  const flush = () => {
    if (run.length >= FOLD_FROM && !all) {
      folded += run.length;
      shown.push({ kind: "muted", text: `${run.length} lines of npm warnings folded` });
    } else {
      shown.push(...run);
    }
    run = [];
  };
  for (const line of lines) {
    const text = line.text.replace(WORKSPACE, "");
    const one = text === line.text ? line : { ...line, text };
    if (one.kind === "info" && WARNING.test(one.text.trim())) {
      run.push(one);
      continue;
    }
    flush();
    shown.push(one);
  }
  flush();
  return { lines: shown, folded };
}

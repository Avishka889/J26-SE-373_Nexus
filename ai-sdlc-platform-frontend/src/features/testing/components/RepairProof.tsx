import { useMemo } from "react";
import { formatWhen } from "@/shared/utils/time";
import { highlightCode } from "@/shared/code-viewer/syntaxHighlight";
import { ProofPair } from "./ProofPair";
import type { Repair } from "../fixtures/types";
import { cn } from "@/shared/utils/cn";

type DiffLine = { text: string; changed: boolean };

/** Smallest honest side-by-side diff: mark the lines that are not in the other version. */
function lineDiff(before: string[], after: string[]): { left: DiffLine[]; right: DiffLine[] } {
  const m = before.length;
  const n = after.length;
  const dp: number[][] = Array.from({ length: m + 1 }, () => new Array(n + 1).fill(0));

  for (let i = m - 1; i >= 0; i -= 1) {
    for (let j = n - 1; j >= 0; j -= 1) {
      dp[i][j] = before[i] === after[j] ? dp[i + 1][j + 1] + 1 : Math.max(dp[i + 1][j], dp[i][j + 1]);
    }
  }

  const left: DiffLine[] = [];
  const right: DiffLine[] = [];
  let i = 0;
  let j = 0;

  while (i < m && j < n) {
    if (before[i] === after[j]) {
      left.push({ text: before[i], changed: false });
      right.push({ text: after[j], changed: false });
      i += 1;
      j += 1;
    } else if (dp[i + 1][j] >= dp[i][j + 1]) {
      left.push({ text: before[i], changed: true });
      i += 1;
    } else {
      right.push({ text: after[j], changed: true });
      j += 1;
    }
  }
  while (i < m) {
    left.push({ text: before[i], changed: true });
    i += 1;
  }
  while (j < n) {
    right.push({ text: after[j], changed: true });
    j += 1;
  }

  return { left, right };
}

function CodeColumn({
  label,
  lines,
  language,
  side,
}: {
  label: string;
  lines: DiffLine[];
  language: "java" | "tsx";
  side: "before" | "after";
}) {
  const html = useMemo(
    () => highlightCode(lines.map((l) => l.text).join("\n"), language, true),
    [lines, language]
  );

  const mark = side === "before" ? "−" : "+";
  const markColor = side === "before" ? "var(--tp-console-fail)" : "var(--tp-console-pass)";
  const rowTint = side === "before" ? "rgba(248,113,113,0.10)" : "rgba(74,222,128,0.10)";

  return (
    <div className="min-w-0 flex-1">
      <div
        className="flex items-center gap-2 border-b px-3 py-2"
        style={{ borderColor: "var(--tp-console-line)" }}
      >
        <span className="tp-console-label">{label}</span>
        <span className="tp-mono ml-auto text-[10px]" style={{ color: "var(--tp-console-muted)" }}>
          {lines.filter((l) => l.changed).length} changed
        </span>
      </div>
      <div className="overflow-x-auto py-2">
        {html.map((line, i) => (
          <div
            key={i}
            className="flex gap-2 font-mono text-[11.5px] leading-[1.6]"
            style={lines[i]?.changed ? { background: rowTint } : undefined}
          >
            <span
              className="w-[2ch] shrink-0 select-none pl-2 text-center"
              style={{ color: lines[i]?.changed ? markColor : "transparent" }}
            >
              {mark}
            </span>
            <span
              className="min-w-0 whitespace-pre pr-3"
              dangerouslySetInnerHTML={{ __html: line || "&nbsp;" }}
            />
          </div>
        ))}
      </div>
    </div>
  );
}

/** Two versions of the same code, side by side, on the runner's own surface. */
export function CodeDiff({
  before,
  after,
  language,
  beforeLabel,
  afterLabel,
  className,
}: {
  before: string;
  after: string;
  language: "java" | "tsx";
  beforeLabel: string;
  afterLabel: string;
  className?: string;
}) {
  const diff = useMemo(() => lineDiff(before.split("\n"), after.split("\n")), [before, after]);

  return (
    <div className={cn("tp-console overflow-hidden rounded-xl", className)}>
      <div className="flex flex-col sm:flex-row">
        <CodeColumn label={beforeLabel} lines={diff.left} language={language} side="before" />
        <div className="h-px w-full sm:h-auto sm:w-px" style={{ background: "var(--tp-console-line)" }} />
        <CodeColumn label={afterLabel} lines={diff.right} language={language} side="after" />
      </div>
    </div>
  );
}

type DiffTone = "header" | "hunk" | "added" | "removed" | "context";

function toneOf(line: string): DiffTone {
  if (line.startsWith("+++") || line.startsWith("---")) return "header";
  if (line.startsWith("@@")) return "hunk";
  if (line.startsWith("+")) return "added";
  if (line.startsWith("-")) return "removed";
  return "context";
}

const DIFF_TONE: Record<DiffTone, { color?: string; background?: string }> = {
  header: { color: "var(--tp-console-muted)" },
  hunk: { color: "var(--tp-console-muted)" },
  added: { color: "var(--tp-console-pass)", background: "rgba(74,222,128,0.10)" },
  removed: { color: "var(--tp-console-fail)", background: "rgba(248,113,113,0.10)" },
  context: {},
};

/**
 * A patch as it was written: one unified diff per file, read line by line.
 *
 * Not rebuilt into before and after, because the hunks are the change the
 * reader is asked to apply, and a reconstruction would show them something
 * the patch never said.
 */
export function UnifiedDiff({
  hunks,
  className,
}: {
  hunks: { path: string; diff: string }[];
  className?: string;
}) {
  return (
    <div className={cn("tp-console overflow-hidden rounded-xl", className)}>
      {hunks.map((hunk, index) => (
        <div key={`${hunk.path}:${index}`} className={index > 0 ? "border-t" : undefined} style={{ borderColor: "var(--tp-console-line)" }}>
          <div className="border-b px-3 py-2" style={{ borderColor: "var(--tp-console-line)" }}>
            <span className="tp-console-label break-all">{hunk.path}</span>
          </div>
          <pre className="overflow-x-auto py-2 font-mono text-[11.5px] leading-[1.6]">
            {hunk.diff.split("\n").map((line, at) => (
              <span key={at} className="block whitespace-pre px-3" style={DIFF_TONE[toneOf(line)]}>
                {line || " "}
              </span>
            ))}
          </pre>
        </div>
      ))}
    </div>
  );
}

/**
 * The one thing this page should be remembered by: a proposed test repair
 * shown next to the run that proves it still catches a planted bug.
 * One dark artifact - the diff and the receipt underneath it are both the
 * runner talking, so they share a surface.
 */
export function RepairProof({ repair, className }: { repair: Repair; className?: string }) {
  const holds = repair.guard.unchanged.pass && repair.guard.planted.pass;

  return (
    <div className={cn("space-y-2.5", className)}>
      {repair.original ? (
        <CodeDiff
          before={repair.original}
          after={repair.proposed}
          language={repair.language}
          beforeLabel="Test today"
          afterLabel="Proposed repair"
        />
      ) : (
        // Live, the repair is known as its patch. Laid out as before and after,
        // it showed an empty "before" and the raw diff as "after".
        <UnifiedDiff hunks={[{ path: repair.path ?? "the test file", diff: repair.proposed }]} />
      )}

      <ProofPair
        dark
        label="Honesty guard"
        meta={`two checks · ran ${formatWhen(repair.proposedAt)}`}
        left={{
          label: "Unchanged code",
          state: repair.guard.unchanged.pass ? "pass" : "fail",
          detail: repair.guard.unchanged.detail,
        }}
        right={{
          label: "Planted bug",
          state: repair.guard.planted.pass ? "pass" : "fail",
          detail: repair.guard.planted.detail,
        }}
        verdict={{ state: holds ? "pass" : "fail", text: repair.verdictLine }}
      />
    </div>
  );
}

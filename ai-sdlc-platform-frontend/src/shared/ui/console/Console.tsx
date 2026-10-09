import { useEffect, useRef, type ReactNode } from "react";
import { cn } from "@/shared/utils/cn";

/**
 * One line of a run transcript.
 *
 * Defined here rather than in the feature that first needed it, because the
 * component is shared and shared code cannot read a feature's types. Testing
 * re-exports it so its own imports did not have to move.
 */
export type ConsoleLine = {
  kind: "cmd" | "info" | "pass" | "fail" | "skip" | "detail" | "summary" | "muted";
  text: string;
};

/**
 * A terminal for real output.
 *
 * Promoted out of Testing when the code phase needed it for build logs: the
 * sandbox produces exactly this shape, a capped tail of real lines, and a
 * second implementation would have drifted on the one thing that matters,
 * which is that what is shown is what the process actually printed.
 */
const consolePrefix: Record<ConsoleLine["kind"], { token: string; color: string; text: string }> = {
  cmd: { token: "$", color: "var(--tp-console-muted)", text: "var(--tp-console-ink)" },
  info: { token: "»", color: "var(--tp-console-muted)", text: "var(--tp-console-ink)" },
  pass: { token: "PASS", color: "var(--tp-console-pass)", text: "var(--tp-console-ink)" },
  fail: { token: "FAIL", color: "var(--tp-console-fail)", text: "var(--tp-console-ink)" },
  skip: { token: "SKIP", color: "var(--tp-console-caution)", text: "var(--tp-console-muted)" },
  detail: { token: "↳", color: "var(--tp-console-muted)", text: "var(--tp-console-fail)" },
  summary: { token: "", color: "var(--tp-console-muted)", text: "var(--tp-console-ink)" },
  muted: { token: "", color: "var(--tp-console-muted)", text: "var(--tp-console-muted)" },
};

export function Console({
  lines,
  streaming,
  label = "Run transcript",
  meta,
  className,
  action,
}: {
  lines: ConsoleLine[];
  streaming?: boolean;
  label?: string;
  meta?: string;
  className?: string;
  action?: ReactNode;
}) {
  const bodyRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    if (!streaming) return;
    const body = bodyRef.current;
    if (body) body.scrollTop = body.scrollHeight;
  }, [lines.length, streaming]);

  return (
    <div className={cn("tp-console flex min-h-0 flex-col overflow-hidden rounded-xl", className)}>
      <div className="flex items-center gap-2 border-b border-[color:var(--tp-console-line)] px-3 py-2">
        <span className="tp-console-label">{label}</span>
        {meta && (
          <span className="tp-mono truncate text-[11px]" style={{ color: "var(--tp-console-muted)" }}>
            {meta}
          </span>
        )}
        <span className="ml-auto">{action}</span>
      </div>
      <div ref={bodyRef} className="min-h-0 flex-1 overflow-auto px-3 py-2.5">
        {lines.map((line, i) => {
          const style = consolePrefix[line.kind];
          return (
            <div
              key={`${i}-${line.text}`}
              className={cn(
                "flex gap-2 py-[1px] font-mono text-[11.5px] leading-[1.6]",
                streaming && i === lines.length - 1 && "tp-stream",
                line.kind === "summary" && "mt-2 border-t border-[color:var(--tp-console-line)] pt-2 font-medium"
              )}
            >
              <span className="w-[4ch] shrink-0 text-right" style={{ color: style.color }}>
                {style.token}
              </span>
              <span className="min-w-0 break-words" style={{ color: style.text }}>
                {line.text}
              </span>
            </div>
          );
        })}
        {streaming && (
          <div className="flex gap-2 font-mono text-[11.5px] leading-[1.6]">
            <span className="w-[4ch] shrink-0" />
            <span className="tp-caret" style={{ color: "var(--tp-console-ink)" }}>
              ▍
            </span>
          </div>
        )}
      </div>
    </div>
  );
}

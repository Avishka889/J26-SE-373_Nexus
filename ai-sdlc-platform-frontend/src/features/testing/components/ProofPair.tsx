import type { ReactNode } from "react";
import { AlertTriangle, Check, ShieldAlert, ShieldCheck, X } from "lucide-react";
import { cn } from "@/shared/utils/cn";
import type { ProofState } from "../fixtures/types";
import { SpinnerIcon } from "@/shared/ui/Spinner";
import { formatWhen } from "@/shared/utils/time";

export type ProofCell = {
  label: string;
  state: ProofState;
  detail: string;
  at?: string;
};

/**
 * Two pieces of evidence either side of a spine, and one verdict underneath
 * that only reads green when both hold. The page uses this shape twice: for
 * the honesty guard on a test repair, and for the two proofs on a security fix.
 */
export function ProofPair({
  label,
  meta,
  left,
  right,
  verdict,
  dark,
  className,
  footer,
}: {
  label: string;
  meta?: string;
  left: ProofCell;
  right: ProofCell;
  verdict: { state: ProofState; text: string };
  dark?: boolean;
  className?: string;
  footer?: ReactNode;
}) {
  const lineColor = dark ? "var(--tp-console-line)" : "var(--tp-line)";
  const labelColor = dark ? "var(--tp-console-muted)" : "var(--tp-muted)";
  const inkColor = dark ? "var(--tp-console-ink)" : "var(--tp-ink)";
  const passColor = dark ? "var(--tp-console-pass)" : "var(--tp-pass)";
  const failColor = dark ? "var(--tp-console-fail)" : "var(--tp-fail)";
  const cautionColor = dark ? "var(--tp-console-caution)" : "var(--tp-caution)";
  const labelClass = dark ? "tp-console-label" : "tp-label";

  const stateColor = (state: ProofState) =>
    state === "pass"
      ? passColor
      : state === "fail"
      ? failColor
      : state === "errored"
      ? cautionColor
      : state === "running"
      ? cautionColor
      : labelColor;

  const stateWord = (state: ProofState) =>
    state === "pass"
      ? "PASS"
      : state === "fail"
      ? "FAIL"
      : state === "errored"
      ? "ERROR"
      : state === "running"
      ? "RUNNING"
      : "QUEUED";

  const StateIcon = (state: ProofState) =>
    state === "pass"
      ? Check
      : state === "fail"
      ? X
      : state === "errored"
      ? AlertTriangle
      : state === "running"
      ? SpinnerIcon
      : Check;

  const cell = (c: ProofCell, side: "left" | "right") => {
    const Icon = StateIcon(c.state);
    return (
      <div
        className={cn(
          "min-w-0 flex-1 p-3.5",
          side === "left" ? "border-b sm:border-b-0 sm:border-r" : ""
        )}
        style={{ borderColor: lineColor }}
      >
        <div className="flex items-center gap-2">
          <span className={labelClass} style={{ color: labelColor }}>
            {c.label}
          </span>
          <span
            className="ml-auto inline-flex items-center gap-1 font-mono text-[10px] font-semibold tracking-[0.14em]"
            style={{ color: stateColor(c.state) }}
          >
            <Icon className="h-3 w-3" />
            {stateWord(c.state)}
          </span>
        </div>
        <p className="mt-2 font-mono text-[11.5px] leading-[1.6]" style={{ color: inkColor }}>
          {c.detail}
        </p>
        {c.at && (
          <p className="mt-1.5 font-mono text-[10px]" style={{ color: labelColor }}>
            {formatWhen(c.at)}
          </p>
        )}
      </div>
    );
  };

  const VerdictIcon =
    verdict.state === "pass"
      ? ShieldCheck
      : verdict.state === "fail"
      ? ShieldAlert
      : verdict.state === "errored"
      ? AlertTriangle
      : SpinnerIcon;

  return (
    <div
      className={cn("overflow-hidden rounded-xl", dark ? "tp-console" : "border border-[color:var(--tp-line)]", className)}
    >
      <div className="flex items-center gap-2 border-b px-3.5 py-2" style={{ borderColor: lineColor }}>
        <span className={labelClass} style={{ color: labelColor }}>
          {label}
        </span>
        {meta && (
          <span className="tp-mono truncate text-[10px]" style={{ color: labelColor }}>
            {meta}
          </span>
        )}
      </div>

      <div className="flex flex-col sm:flex-row">
        {cell(left, "left")}
        {cell(right, "right")}
      </div>

      <div
        className="flex items-start gap-2.5 border-t px-3.5 py-3"
        style={{ borderColor: lineColor, background: dark ? "var(--tp-console-2)" : "var(--tp-surface-2)" }}
      >
        <VerdictIcon
          className="mt-px h-4 w-4 shrink-0"
          style={{ color: stateColor(verdict.state) }}
        />
        <p
          className="text-[13px] font-medium leading-snug"
          style={{ color: verdict.state === "pending" || verdict.state === "running" ? inkColor : stateColor(verdict.state) }}
        >
          {verdict.text}
        </p>
      </div>

      {footer && (
        <div className="border-t px-3.5 py-2.5" style={{ borderColor: lineColor }}>
          {footer}
        </div>
      )}
    </div>
  );
}

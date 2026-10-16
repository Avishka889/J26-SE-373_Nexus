import { type ReactNode } from "react";
import { ArrowRight } from "lucide-react";
import { cn } from "@/shared/utils/cn";
import { Card } from "@/shared/ui/primitives";
import { mutationTile, type StepId, type TestingView } from "../model/view";

/* ---------------------------------------------------------- summary strip */

type Cell = {
  label: string;
  value: ReactNode;
  denominator?: ReactNode;
  note?: ReactNode;
  tone?: "pass" | "fail" | "caution" | "muted";
  goTo?: StepId;
  goToLabel?: string;
};

export function SummaryStrip({
  view,
  onGoTo,
}: {
  view: TestingView;
  onGoTo: (step: StepId) => void;
}) {
  const waiting = view.streaming;
  const dash = <span className="text-[color:var(--tp-muted)]">-</span>;

  const cells: Cell[] = [
    {
      label: "Tests passing",
      value: view.totals.passed,
      denominator: `of ${view.totals.run} run`,
      note: `pass rate ${view.totals.passRate.toFixed(1)}%`,
    },
    {
      label: "Failing",
      value: view.totals.failed,
      tone: view.totals.failed > 0 ? "fail" : "pass",
      note:
        view.totals.failed > 0 ? "open the failure inbox" : "nothing failing",
      goTo: view.totals.failed > 0 ? "self-healing" : undefined,
      goToLabel: "Open the failure inbox",
    },
    {
      label: "Repairs awaiting you",
      value: waiting ? dash : view.inbox.awaiting,
      tone: view.inbox.awaiting > 0 ? "caution" : undefined,
      note: waiting
        ? "waiting on this run"
        : view.inbox.awaiting > 0
          ? "review in the inbox"
          : "none in the queue",
      goTo: !waiting && view.inbox.awaiting > 0 ? "self-healing" : undefined,
      goToLabel: "Review the repair queue",
    },
    {
      label: "Mutation score",
      value: waiting ? dash : mutationTile(view.quality).value,
      note: waiting ? "waiting on this run" : mutationTile(view.quality).note,
      goTo: waiting ? undefined : "test-quality",
      goToLabel: "See test quality",
    },
    {
      label: "Findings to resolve",
      value: waiting ? dash : view.findingCounts.toResolve,
      denominator: waiting ? undefined : `of ${view.findings.length}`,
      tone: view.findingCounts.toResolve > 0 ? "caution" : "pass",
      note: waiting
        ? "waiting on this run"
        : `${view.findingCounts.open} open · ${view.findingCounts.proposed} fix proposed · ${view.findingCounts.applied} fix applied`,
      goTo: waiting ? undefined : "security-scan",
      goToLabel: "See security findings",
    },
  ];

  return (
    // By the column's width, not the window's. Beside the conversation the
    // column is 650 to 880 pixels on a window wide enough for five across, and
    // five tiles there wrapped "Not measured" and cut their labels short.
    <div className="@container">
    <div data-summary-tiles className="grid grid-cols-2 gap-3 @xl:grid-cols-3 @5xl:grid-cols-5">
      {cells.map((cell) => {
        const color =
          cell.tone === "pass"
            ? "var(--tp-pass)"
            : cell.tone === "fail"
              ? "var(--tp-fail)"
              : cell.tone === "caution"
                ? "var(--tp-caution)"
                : undefined;

        const body = (
          <>
            <p className="tp-label truncate">{cell.label}</p>
            <p className="mt-0.5 flex items-baseline gap-1.5">
              <span
                className="tp-num text-xl"
                style={color ? { color } : undefined}
              >
                {cell.value}
              </span>
              {cell.denominator && (
                <span className="tp-den">{cell.denominator}</span>
              )}
            </p>
            {cell.note && (
              <p className="tp-den mt-0.5 flex items-start gap-1 leading-snug">
                <span>{cell.note}</span>
                {cell.goTo && (
                  <ArrowRight className="mt-px h-3 w-3 shrink-0 opacity-0 transition-opacity group-hover:opacity-100" />
                )}
              </p>
            )}
          </>
        );

        return cell.goTo ? (
          <button
            key={cell.label}
            type="button"
            aria-label={cell.goToLabel}
            onClick={() => onGoTo(cell.goTo!)}
            className="group text-left"
          >
            <Card className="h-full px-3.5 py-2.5 hover:border-blue-500/40">
              {body}
            </Card>
          </button>
        ) : (
          <Card key={cell.label} className="px-3.5 py-2.5">
            {body}
          </Card>
        );
      })}
    </div>
    </div>
  );
}

/* ---------------------------------------------------------- sticky header */

export function StickyHeader({
  children,
  className,
}: {
  children: ReactNode;
  className?: string;
}) {
  return (
    <div
      className={cn(
        "z-[11] -mx-6 space-y-3 bg-white px-6 pb-3 dark:bg-[#071018] md:-mx-8 md:px-8 lg:sticky",
        className,
      )}
      style={{ top: 0 }}
    >
      {children}
    </div>
  );
}

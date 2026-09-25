import { ArrowUpRight, ClipboardCheck } from "lucide-react";
import { cn } from "@/shared/utils/cn";
import { Panel } from "../../bits/index";
import { counted, mutationTile, type StepId, type TestingView } from "../../../model/view";
import { formatWhen } from "@/shared/utils/time";

function SummaryCell({
  label,
  value,
  denominator,
  note,
  tone,
  onClick,
  className,
}: {
  label: string;
  value: string | number;
  denominator?: string;
  note?: string;
  tone?: "pass" | "fail" | "caution";
  onClick?: () => void;
  className?: string;
}) {
  const color =
    tone === "pass" ? "var(--tp-pass)" : tone === "fail" ? "var(--tp-fail)" : tone === "caution" ? "var(--tp-caution)" : undefined;

  return (
    <button
      type="button"
      onClick={onClick}
      className={cn(
        "group border-b border-r border-slate-100 px-4 py-3 text-left transition-colors hover:bg-slate-50 dark:border-white/[0.04] dark:hover:bg-white/[0.02]",
        className
      )}
    >
      <p className="tp-label flex items-center gap-1 truncate">
        {label}
        <ArrowUpRight className="h-2.5 w-2.5 opacity-0 transition-opacity group-hover:opacity-100" />
      </p>
      <p className="mt-1.5 flex items-baseline gap-1.5">
        <span className="tp-num text-2xl" style={color ? { color } : undefined}>
          {value}
        </span>
        {denominator && <span className="tp-den">{denominator}</span>}
      </p>
      {note && <p className="tp-den mt-0.5 truncate">{note}</p>}
    </button>
  );
}

export function ReportSummaryGrid({
  view,
  runSprint,
  runBranch,
  onGoTo,
}: {
  view: TestingView;
  /** The demo's sprint and branch. A live run has neither, and names its test version. */
  runSprint?: string;
  runBranch?: string;
  onGoTo: (step: StepId) => void;
}) {
  const severity = {
    critical: view.findings.filter((f) => f.severity === "critical").length,
    high: view.findings.filter((f) => f.severity === "high").length,
  };

  return (
    <Panel
      icon={<ClipboardCheck className="h-4 w-4 text-blue-400" />}
      label="Validation summary"
      title={runSprint ? `${runSprint} · Build ${view.build}` : `Test version ${view.build}`}
      meta={`Suite finished ${formatWhen(view.finishedAt)} · ${view.duration}${runBranch ? ` · branch ${runBranch}` : ""}`}
      bodyClassName="p-0"
    >
      <div className="grid grid-cols-2 border-t border-slate-100 dark:border-white/[0.04] lg:grid-cols-4">
        <SummaryCell
          label="Tests passing"
          value={view.totals.passed}
          denominator={`of ${view.totals.run} run`}
          note={`pass rate ${view.totals.passRate.toFixed(1)}% · ${view.totals.skipped} skipped`}
          onClick={() => onGoTo("test-run")}
        />
        <SummaryCell
          label="Failing"
          value={view.totals.failed}
          tone={view.totals.failed > 0 ? "fail" : "pass"}
          // The third kind is the one a first run has, and it was left out:
          // three failures read "0 brittle, 0 real regressions".
          note={[
            `${view.inbox.brittle} brittle`,
            `${view.inbox.regressions} real regressions`,
            ...(view.inbox.unclassified > 0 ? [`${view.inbox.unclassified} not classified`] : []),
          ].join(" · ")}
          onClick={() => onGoTo("self-healing")}
        />
        <SummaryCell
          label="Repairs awaiting you"
          value={view.inbox.awaiting}
          tone={view.inbox.awaiting > 0 ? "caution" : "pass"}
          note={`${view.decisions.approved} approved · ${view.decisions.rejected} rejected`}
          onClick={() => onGoTo("self-healing")}
        />
        <SummaryCell
          label="Healed"
          value={view.inbox.healed}
          note="repairs verified and merged"
          onClick={() => onGoTo("self-healing")}
        />
        <SummaryCell
          label="Line coverage"
          value={`${view.quality.line.percent}%`}
          note={`${view.quality.line.covered.toLocaleString()} of ${view.quality.line.total.toLocaleString()} lines`}
          onClick={() => onGoTo("test-quality")}
        />
        <SummaryCell
          label="Branch coverage"
          value={`${view.quality.branch.percent}%`}
          note={`${view.quality.branch.covered.toLocaleString()} of ${view.quality.branch.total.toLocaleString()} branches`}
          onClick={() => onGoTo("test-quality")}
        />
        <SummaryCell
          label="Mutation score"
          value={mutationTile(view.quality).value}
          note={mutationTile(view.quality).note}
          onClick={() => onGoTo("test-quality")}
        />
        <SummaryCell
          label="Findings to resolve"
          value={view.findingCounts.toResolve}
          denominator={`of ${view.findings.length}`}
          tone={view.findingCounts.toResolve > 0 ? "caution" : "pass"}
          note={`${severity.critical} critical · ${severity.high} high · ${view.findingCounts.verified} re-verified`}
          onClick={() => onGoTo("security-scan")}
        />
      </div>
      <p className="tp-den px-4 py-3 leading-relaxed">
        Decisions logged at test version {view.build}:{" "}
        {counted(view.decisions.approved, "repair", "repairs")} approved, {view.decisions.rejected} rejected,{" "}
        {counted(view.decisions.applied, "fix", "fixes")} applied,{" "}
        {counted(view.decisions.dismissed, "finding", "findings")} dismissed. Approving the phase is a review of these
        decisions, not a new one.
        {view.awaitingRerun > 0 &&
          ` ${view.awaitingRerun} approved ${view.awaitingRerun === 1 ? "repair is" : "repairs are"} counted as passing from the guard run, and the next run records ${view.awaitingRerun === 1 ? "it" : "them"}.`}
      </p>
    </Panel>
  );
}

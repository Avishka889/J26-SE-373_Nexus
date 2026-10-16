import { useState } from "react";
import { Check, GitCompare, ShieldOff, X } from "lucide-react";
import { cn } from "@/shared/utils/cn";
import { Badge, Card, CardContent, Td, Th } from "@/shared/ui/primitives";
import { Note, Panel, severityLabel } from "../bits/index";
import type { DetectorComparison, Severity } from "../../fixtures/types";
import { atLine, counted, type RefusedCandidate, type StepId, type TestingView } from "../../model/view";
import { SecurityFindingsList } from "./security/SecurityFindingsList";
import { StageSection } from "@/shared/ui/stage";

const severityTile: Record<Severity, { border: string; text: string }> = {
  critical: { border: "border-red-500/30", text: "text-red-500 dark:text-red-400" },
  high: { border: "border-orange-500/30", text: "text-orange-500 dark:text-orange-400" },
  medium: { border: "border-amber-500/30", text: "text-amber-500 dark:text-amber-400" },
  low: {
    border: "border-slate-300 dark:border-white/10",
    text: "text-slate-500 dark:text-slate-400",
  },
  none: {
    border: "border-slate-300 dark:border-white/10",
    text: "text-slate-500 dark:text-slate-400",
  },
};

/** Why a candidate was refused, in words; a reason with none of its own reads as itself. */
const REFUSAL_WORDS: Record<string, string> = {
  "no-evidence": "no line of the repository was given",
  "file-not-found": "the file it names is not in the repository",
  "span-out-of-range": "the lines it names are past the end of the file",
  "snippet-does-not-match": "the code it quotes is not at that place",
  "malformed-cwe": "its CWE is not one",
};

/** How many refused candidates show before the rest are asked for. */
const REFUSED_SHOWN = 5;

/**
 * The candidates the scan threw away, and why each was.
 *
 * A candidate becomes a finding only when its evidence resolves to a line of
 * the repository, and the ones that do not are counted on the report. They
 * were drawn nowhere: twelve npm audit advisories were refused on a live run,
 * and the page read "0 findings" with no word of them.
 */
function RefusedCandidates({ refused }: { refused: RefusedCandidate[] }) {
  const [all, setAll] = useState(false);
  if (refused.length === 0) return null;
  const shown = all ? refused : refused.slice(0, REFUSED_SHOWN);
  const advisories = refused.some((one) => one.detail.startsWith("npm audit:"));

  return (
    <Panel
      className="mt-4"
      icon={<ShieldOff className="h-4 w-4 text-slate-400" />}
      label="Not shown as findings"
      title={`${counted(refused.length, "candidate", "candidates")} ${refused.length === 1 ? "was" : "were"} refused`}
      meta="A candidate becomes a finding only when its evidence resolves to a line of this repository. These did not, so they are counted here and not above."
    >
      {advisories && (
        <Note className="max-w-3xl">
          npm audit reports an advisory against a package, not a line, so every one of its
          advisories is refused by that rule. They are listed so they are not lost: read them as
          dependency advisories, which Deployment&apos;s dependency analysis also weighs.
        </Note>
      )}
      <ul className={advisories ? "mt-3 divide-y divide-[color:var(--tp-line)]" : "divide-y divide-[color:var(--tp-line)]"}>
        {shown.map((one, index) => (
          <li key={`${one.cwe}:${one.path}:${index}`} className="py-2.5">
            <p className="break-words text-[13px] text-[color:var(--tp-ink)]">{one.detail || one.cwe}</p>
            <p className="tp-den mt-0.5 break-words">
              {[
                one.cwe,
                REFUSAL_WORDS[one.reason] ?? one.reason,
                one.path && `claimed in ${atLine(one.path, one.line)}`,
              ]
                .filter(Boolean)
                .join(" · ")}
            </p>
          </li>
        ))}
      </ul>
      {refused.length > REFUSED_SHOWN && !all && (
        <button
          type="button"
          onClick={() => setAll(true)}
          className="mt-2 text-xs font-medium text-blue-600 underline underline-offset-2 dark:text-blue-400"
        >
          Show all {refused.length}
        </button>
      )}
    </Panel>
  );
}

export function StepSecurity({
  view,
  severityOrder,
  detectorComparison,
  expandedId,
  onExpand,
  onApplyFix,
  onDismiss,
  onAccept,
  onGoTo,
}: {
  view: TestingView;
  severityOrder: Severity[];
  /** The detectors' measured comparison, or null where nothing measured one. */
  detectorComparison: DetectorComparison | null;
  expandedId: string | null;
  onExpand: (id: string | null) => void;
  /** Resolves false when the server refused, so the detail can keep its state. */
  onApplyFix: (id: string) => Promise<boolean> | void;
  onDismiss: (id: string, reason: string) => Promise<boolean> | void;
  /** Accept a finding's risk with the reason it can ship as it is (G8). */
  onAccept: (id: string, reason: string) => Promise<boolean> | void;
  onGoTo: (step: StepId) => void;
}) {
  const counts = severityOrder.map((s) => ({
    severity: s,
    count: view.findings.filter((f) => f.severity === s).length,
  }));

  const statusRows = [
    { label: "Open", count: view.findingCounts.open, color: "#94a3b8" },
    { label: "Fix proposed", count: view.findingCounts.proposed, color: "#3b82f6" },
    // Short enough to be read whole: "Fix applied, not yet r..." was cut off.
    { label: "Applied, not re-verified", count: view.findingCounts.applied, color: "#f59e0b" },
    { label: "Fixed and re-verified", count: view.findingCounts.verified, color: "#10b981" },
    ...(view.findingCounts.dismissed
      ? [{ label: "Dismissed", count: view.findingCounts.dismissed, color: "#cbd5e1" }]
      : []),
  ];
  const total = view.findings.length || 1;

  return (
    <div className="space-y-4">
      <StageSection id="security-counts">
        <div className="grid grid-cols-1 gap-4 lg:grid-cols-[minmax(0,1.3fr)_minmax(0,1fr)]">
          <div className="grid grid-cols-2 gap-4 sm:grid-cols-4">
            {counts.map(({ severity, count }) => (
              <Card key={severity} className={cn("self-start", severityTile[severity].border)}>
                <CardContent className="p-4">
                  <p className="tp-label">{severityLabel[severity]}</p>
                  <p
                    className={cn(
                      "mt-1 text-2xl font-bold tabular-nums",
                      count > 0
                        ? severityTile[severity].text
                        : "text-slate-500 dark:text-slate-400",
                    )}
                  >
                    {count}
                  </p>
                </CardContent>
              </Card>
            ))}
          </div>

          <Card>
            <CardContent className="p-4">
              <p className="tp-label">Findings by status</p>
              <div className="mt-2.5 flex h-2 w-full overflow-hidden rounded-full bg-slate-100 dark:bg-white/10">
                {statusRows.map((row) =>
                  row.count > 0 ? (
                    <span
                      key={row.label}
                      title={`${row.label}: ${row.count}`}
                      style={{ width: `${(row.count / total) * 100}%`, background: row.color }}
                    />
                  ) : null,
                )}
              </div>
              <ul className="mt-2.5 grid grid-cols-2 gap-x-4">
                {statusRows.map((row) => (
                  <li key={row.label} className="flex items-center gap-2 py-0.5">
                    <span
                      className="h-1.5 w-1.5 shrink-0 rounded-full"
                      style={{ background: row.color }}
                    />
                    <span className="tp-den truncate">{row.label}</span>
                    <span className="ml-auto text-[13px] tabular-nums">{row.count}</span>
                  </li>
                ))}
              </ul>
            </CardContent>
          </Card>
        </div>
      </StageSection>

      {view.scanTools.length > 0 && (
        <ul className="space-y-0.5">
          {view.scanTools.map((line) => (
            <li key={line} className="tp-den">
              {line}
            </li>
          ))}
        </ul>
      )}

      <StageSection id="security-findings">
        <SecurityFindingsList
          findings={view.findings}
          build={view.build}
          toResolve={view.findingCounts.toResolve}
          refused={view.refused.length}
          tools={view.scanTools
            .filter((one) => one.endsWith(" ran"))
            .map((one) => one.slice(0, -" ran".length))}
          fixShipsWith={view.fixShipsWith}
          fixAwaitingItsRun={view.fixAwaitingItsRun}
          expandedId={expandedId}
          onExpand={onExpand}
          onApplyFix={onApplyFix}
          onDismiss={onDismiss}
          onAccept={onAccept}
          onGoTo={onGoTo}
        />
        <RefusedCandidates refused={view.refused} />
      </StageSection>

      {detectorComparison && (
        <StageSection id="security-detectors">
          <Panel
            icon={<GitCompare className="h-4 w-4 text-blue-400" />}
            label="Detector comparison"
            title="Why both detectors run"
            meta="One is fast, free and stays on your machine. The other reads more carefully. Together they miss the least."
            bodyClassName="p-0"
          >
            <div className="w-full overflow-auto">
              <table className="w-full min-w-[640px] text-sm">
                <thead>
                  <tr>
                    <Th>Detector</Th>
                    <Th className="text-right">Precision</Th>
                    <Th className="text-right">Recall</Th>
                    <Th className="text-right">F1</Th>
                    <Th className="text-right">Cost per scan</Th>
                    <Th className="text-right">Median latency</Th>
                    <Th>Runs offline</Th>
                  </tr>
                </thead>
                <tbody>
                  {detectorComparison.rows.map((row, i) => {
                    const best = i === detectorComparison.rows.length - 1;
                    return (
                      <tr key={row.detector} className={cn(best && "bg-blue-500/5")}>
                        <Td className={cn("text-[13px]", best && "font-semibold")}>{row.detector}</Td>
                        <Td className="text-right tabular-nums">{row.precision.toFixed(2)}</Td>
                        <Td className="text-right tabular-nums">{row.recall.toFixed(2)}</Td>
                        <Td className="text-right tabular-nums">{row.f1.toFixed(2)}</Td>
                        <Td className="text-right tabular-nums">{row.cost}</Td>
                        <Td className="text-right tabular-nums">{row.latency}</Td>
                        <Td>
                          {row.offline ? (
                            <Badge variant="success">
                              <Check className="h-3 w-3" />
                              Yes
                            </Badge>
                          ) : (
                            <Badge variant="default">
                              <X className="h-3 w-3" />
                              No
                            </Badge>
                          )}
                        </Td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
            <p className="tp-den border-t border-[color:var(--tp-line)] px-5 py-3 leading-relaxed">
              {detectorComparison.caption}
            </p>
          </Panel>
        </StageSection>
      )}
    </div>
  );
}

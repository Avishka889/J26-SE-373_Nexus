import { Fragment } from "react";
import { ChevronDown, ChevronRight, ShieldAlert } from "lucide-react";
import { cn } from "@/shared/utils/cn";
import { Td, Th } from "@/shared/ui/primitives";
import { FindingStatusChip, Panel, SeverityChip } from "../../bits/index";
import type { Finding } from "../../../fixtures/types";
import { atLine, counted, shortPath, type StepId } from "../../../model/view";
import { SecurityFindingDetail } from "./SecurityFindingDetail";

export function SecurityFindingsList({
  findings,
  build,
  toResolve,
  refused = 0,
  tools = [],
  fixShipsWith,
  fixAwaitingItsRun,
  expandedId,
  onExpand,
  onApplyFix,
  onDismiss,
  onAccept,
  onGoTo,
}: {
  findings: Finding[];
  build: number;
  toResolve: number;
  /** How many candidates the scan refused, which are listed under this table. */
  refused?: number;
  /** The scanning tools that ran, by name ("semgrep 1.180.0"), for the heading. */
  tools?: string[];
  /** What a fix applied now ships with, when that is newer code than may ship (C4-13). */
  fixShipsWith?: string | null;
  /** Why no fix can be applied yet, when another fix waits for its run (C3-9). */
  fixAwaitingItsRun?: string | null;
  expandedId: string | null;
  onExpand: (id: string | null) => void;
  /** Resolves false when the server refused, so the detail can keep its state. */
  onApplyFix: (id: string) => Promise<boolean> | void;
  onDismiss: (id: string, reason: string) => Promise<boolean> | void;
  onAccept: (id: string, reason: string) => Promise<boolean> | void;
  onGoTo: (step: StepId) => void;
}) {
  return (
    <Panel
      icon={<ShieldAlert className="h-4 w-4 text-blue-400" />}
      label="Findings"
      // The tools that ran, by name. It said "Two detectors ran and their
      // results were combined" whatever had run.
      title={tools.length > 0 ? `What ${listed(tools)} raised` : "What the scan raised"}
      meta={[
        `${counted(findings.length, "finding", "findings")} at test version ${build}`,
        `${toResolve} still to resolve`,
        // Said beside the count: "0 findings" alone read as "nothing was found".
        ...(refused > 0 ? [`${counted(refused, "candidate", "candidates")} refused, listed below`] : []),
      ].join(" · ")}
      bodyClassName="p-0"
    >
      {findings.length === 0 ? (
        // Said, where a row of headings over nothing was.
        <p className="tp-den border-t border-[color:var(--tp-line)] px-5 py-4 text-[13px]">
          No findings at test version {build}.
        </p>
      ) : (
      <div className="w-full overflow-auto">
        <table className="w-full min-w-[720px] text-sm">
          <thead>
            <tr>
              <Th>CWE</Th>
              <Th>Name</Th>
              <Th>Severity</Th>
              <Th className="text-right">CVSS</Th>
              <Th>Location</Th>
              <Th>Status</Th>
            </tr>
          </thead>
          <tbody>
            {findings.map((finding) => {
              const open = expandedId === finding.id;
              return (
                <Fragment key={finding.id}>
                  <tr
                    className={cn("cursor-pointer transition-colors", open && "bg-blue-500/5")}
                    onClick={() => onExpand(open ? null : finding.id)}
                  >
                    <Td>
                      {/* A button, so a keyboard opens the finding too: the row
                          alone took only a click. */}
                      <button
                        type="button"
                        aria-expanded={open}
                        aria-label={`${finding.cwe}: ${finding.name}`}
                        onClick={(event) => {
                          event.stopPropagation();
                          onExpand(open ? null : finding.id);
                        }}
                        className="flex items-center gap-1.5 rounded outline-none focus-visible:ring-2 focus-visible:ring-blue-500/40"
                      >
                        {open ? (
                          <ChevronDown aria-hidden="true" className="h-3.5 w-3.5 text-slate-500 dark:text-slate-400" />
                        ) : (
                          <ChevronRight aria-hidden="true" className="h-3.5 w-3.5 text-slate-500 dark:text-slate-400" />
                        )}
                        <span className="font-mono text-xs">{finding.cwe}</span>
                      </button>
                    </Td>
                    <Td className="text-[13px]">{finding.name}</Td>
                    <Td>
                      <SeverityChip severity={finding.severity} />
                    </Td>
                    <Td className="text-right tabular-nums">{finding.cvss.toFixed(1)}</Td>
                    <Td className="font-mono text-[11px]">
                      {atLine(shortPath(finding.file), finding.line)}
                    </Td>
                    <Td>
                      <FindingStatusChip status={finding.status} />
                    </Td>
                  </tr>
                  {open && (
                    <tr>
                      <Td colSpan={6} className="bg-slate-50 p-4 dark:bg-white/[0.02]">
                        <SecurityFindingDetail
                          finding={finding}
                          shipsWith={fixShipsWith}
                          applyBlocked={fixAwaitingItsRun}
                          onApplyFix={onApplyFix}
                          onDismiss={onDismiss}
                          onAccept={onAccept}
                          onGoTo={onGoTo}
                        />
                      </Td>
                    </tr>
                  )}
                </Fragment>
              );
            })}
          </tbody>
        </table>
      </div>
      )}
    </Panel>
  );
}

/** "a", "a and b", "a, b and c". */
function listed(names: string[]): string {
  if (names.length <= 1) return names.join("");
  return `${names.slice(0, -1).join(", ")} and ${names[names.length - 1]}`;
}

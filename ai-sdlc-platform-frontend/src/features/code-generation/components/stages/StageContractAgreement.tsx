import { AlertTriangle, CheckCircle2, Info } from "lucide-react";
import { cn } from "@/shared/utils/cn";
import { Metric, Note, Panel } from "@/shared/ui/phase";
import { StageSection } from "@/shared/ui/stage";
import type { AgreementFinding, CodeSnapshot } from "../../api/types";

/**
 * Whether the code and the contract actually agree, checked before anything
 * runs.
 *
 * This is the stage the phase exists to make possible: the generated frontend
 * and backend are read, not executed, and every claim below is a parse of what
 * was written. A finding carries the file and the line it is about, because
 * "somewhere in this file" is not a location.
 *
 * The counts are the numbers the evaluation reports, so nothing here is
 * rounded, softened or inferred from a sample.
 */
export function StageContractAgreement({
  snapshot,
  onOpenLocation,
}: {
  snapshot: CodeSnapshot;
  /** Opens the file a finding cites, at its line: the locations were plain text. */
  onOpenLocation: (path: string, line?: number) => void;
}) {
  const agreement = snapshot.agreement;
  if (!agreement) return null;
  const counts = agreement.counts;
  const source = `the agreement check of code version ${snapshot.codeVersion} against its contract`;
  const errors = agreement.findings.filter((finding) => finding.severity === "error");
  const warnings = agreement.findings.filter((finding) => finding.severity === "warning");

  return (
    <div className="space-y-5">
      <StageSection id="agreement-counts">
        <Panel
          label="Agreement"
          title="Counted by reading the generated sources against the contract."
          icon={
            errors.length === 0 ? (
              <CheckCircle2 className="h-4 w-4" />
            ) : (
              <AlertTriangle className="h-4 w-4" />
            )
          }
        >
          <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
            {/* Registered, not implemented: a route that answers without doing
                anything counts here, so the label says what was counted (C2-3). */}
            <Metric
              source={source}
              label="Routes registered"
              value={`${counts.endpointsImplemented}/${counts.endpointsTotal}`}
            />
            {/* The share registered is the tile beside this one said as a percentage,
                and "Agreement" claimed more than it counts; a form nothing saves is
                what the count misses (C2-3). */}
            <Metric
              source={source}
              label="Forms nothing saves"
              value={String(agreement.findings.filter((finding) => finding.ruleId === "form-not-wired").length)}
            />
            <Metric source={source} label="Called by a page" value={String(counts.endpointsCalled)} />
            <Metric source={source} label="Schema mismatches" value={String(counts.schemaMismatches)} />
          </div>

          <div className="mt-3 grid gap-2 sm:grid-cols-3">
            <CountList label="Not registered" ids={counts.endpointsMissing} tone="error" />
            <CountList label="Never called" ids={counts.endpointsUnused} tone="warning" />
            <CountList label="Routes the contract never declared" ids={counts.orphanRoutes} tone="error" />
          </div>

          {counts.foreignCalls.length > 0 && (
            <div className="mt-3 rounded-xl border border-red-500/30 bg-red-500/5 px-3.5 py-3">
              <p className="text-[13px] font-semibold text-[color:var(--tp-ink)]">
                {counts.foreignCalls.length} file
                {counts.foreignCalls.length === 1 ? "" : "s"} request outside the generated client
              </p>
              <Note className="mt-1">
                Agreement is measured through the client, so a request that goes around it is
                a request nothing can check. {counts.foreignCalls.join(", ")}
              </Note>
            </div>
          )}
        </Panel>
      </StageSection>

      <StageSection id="agreement-findings">
        <Panel label={`Findings (${agreement.findings.length})`}>
          {agreement.findings.length === 0 ? (
            <Note>
              Nothing to report: every contract endpoint is served, every page calls a method
              that exists, and no route was found that the contract never declared.
            </Note>
          ) : (
            <ul className="space-y-2">
              {[...errors, ...warnings].map((finding, index) => (
                <FindingRow
                  key={`${finding.ruleId}-${finding.subject}-${index}`}
                  finding={finding}
                  onOpenLocation={onOpenLocation}
                />
              ))}
            </ul>
          )}
        </Panel>
      </StageSection>
    </div>
  );
}

function CountList({
  label,
  ids,
  tone,
}: {
  label: string;
  ids: string[];
  tone: "error" | "warning";
}) {
  return (
    <div className="rounded-xl border border-[color:var(--tp-line)] px-3 py-2.5">
      <p className="tp-den">{label}</p>
      {ids.length === 0 ? (
        <p className="mt-0.5 text-[13px] font-medium text-[color:var(--tp-ink)]">none</p>
      ) : (
        <ul className="mt-1 space-y-0.5">
          {ids.map((id) => (
            <li
              key={id}
              className={cn(
                "tp-mono text-[11px]",
                tone === "error"
                  ? "text-red-600 dark:text-red-400"
                  : "text-amber-700 dark:text-amber-400",
              )}
            >
              {id}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

function FindingRow({
  finding,
  onOpenLocation,
}: {
  finding: AgreementFinding;
  onOpenLocation: (path: string, line?: number) => void;
}) {
  const isError = finding.severity === "error";
  return (
    <li
      className={cn(
        "rounded-xl border px-3.5 py-3",
        isError ? "border-red-500/30 bg-red-500/5" : "border-amber-500/30 bg-amber-500/5",
      )}
    >
      <div className="flex items-start gap-2.5">
        {isError ? (
          <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0 text-red-500" />
        ) : (
          <Info className="mt-0.5 h-4 w-4 shrink-0 text-amber-500" />
        )}
        <div className="min-w-0 flex-1">
          <p className="text-[13px] text-[color:var(--tp-ink)]">{finding.reason}</p>
          {finding.hint && <Note className="mt-1">{finding.hint}</Note>}
          <div className="mt-1 flex flex-wrap items-center gap-2">
            <span className="tp-mono text-[10.5px] text-[color:var(--tp-muted)]">
              {finding.ruleId}
            </span>
            {finding.location && (
              <button
                type="button"
                onClick={() =>
                  onOpenLocation(finding.location!.path, finding.location!.line || undefined)
                }
                className="tp-mono text-[10.5px] text-blue-700 underline-offset-2 hover:underline dark:text-blue-300"
              >
                {finding.location.path}
                {finding.location.line ? `:${finding.location.line}` : ""}
              </button>
            )}
          </div>
        </div>
      </div>
    </li>
  );
}

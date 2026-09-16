import { useState } from "react";
import { AlertTriangle, Download, GitCompare } from "lucide-react";
import { Button } from "@/shared/ui/primitives";
import { cn } from "@/shared/utils/cn";
import { Chip, Metric, Note, Panel } from "@/shared/ui/phase";
import { StageSection, TraceChips } from "@/shared/ui/stage";
import type { ApiEndpoint, CodeSnapshot } from "../../api/types";

/**
 * The research core's artefact, and the one stage where the reader is asked to
 * compare rather than to accept.
 *
 * Two arms produce the same shape from the same input: a deterministic rule
 * generator and a language model. Both are kept whole, because comparing them
 * is the point and an artefact that kept only the winner would have destroyed
 * its own denominator. Choosing one regenerates the code from it.
 *
 * Every endpoint carries what it was inferred from. An endpoint that traces to
 * nothing is a finding, not a feature, so the traces are rendered on every row
 * rather than implied by a diagram somewhere.
 */
const METHOD_TONE: Record<string, string> = {
  GET: "text-emerald-700 dark:text-emerald-400",
  POST: "text-blue-600 dark:text-blue-300",
  PATCH: "text-amber-700 dark:text-amber-400",
  PUT: "text-amber-700 dark:text-amber-400",
  DELETE: "text-red-600 dark:text-red-400",
};

/** How many conflicts show before "Show all": they were cut at this, with no word. */
const CONFLICTS_SHOWN = 8;

export function StageApiContract({
  snapshot,
  onChooseArm,
  onJumpToScreen,
  onOpenRequirement,
  onDownloadOpenApi,
  busy,
}: {
  snapshot: CodeSnapshot;
  onChooseArm: (arm: "rule" | "llm" | "merged") => void;
  onJumpToScreen: (screenId: string) => void;
  /** Opens the requirement on the design page: the chips did nothing. */
  onOpenRequirement: (requirementId: string) => void;
  /** Saves the contract as the OpenAPI document the server translates it to. */
  onDownloadOpenApi: () => Promise<void>;
  busy: boolean;
}) {
  const [allConflicts, setAllConflicts] = useState(false);
  const [downloading, setDownloading] = useState(false);
  const artefact = snapshot.contract;
  if (!artefact) return null;
  const comparison = artefact.comparison;
  const conflicts = comparison?.conflicts ?? [];

  return (
    <div className="space-y-5">
      <StageSection id="contract-arms">
        <Panel
          label="How this contract was inferred"
          title="Both methods ran on the same screens and the same graph."
        >
          <div className="grid gap-3 sm:grid-cols-2">
            <ArmCard
              name="Rule-based"
              blurb="Deterministic. Screens and action edges map to endpoints by convention, so every endpoint traces by construction."
              endpoints={comparison?.rule.endpoints ?? artefact.ruleArm.endpoints.length}
              errors={artefact.ruleFindings.filter((finding) => finding.severity === "error").length}
              attempts={comparison?.rule.attempts ?? 1}
              chosen={artefact.chosen === "rule"}
              available
              onChoose={() => onChooseArm("rule")}
              busy={busy}
            />
            <ArmCard
              name="AI model"
              blurb="A model, given the same input and the same output shape, checked against the same rule catalogue and repaired once if it broke one."
              endpoints={comparison?.llm.endpoints ?? artefact.llmArm?.endpoints.length ?? 0}
              errors={comparison?.llm.errors ?? 0}
              attempts={comparison?.llm.attempts ?? 0}
              chosen={artefact.chosen === "llm"}
              available={Boolean(artefact.llmArm)}
              failure={artefact.llmFailure}
              onChoose={() => onChooseArm("llm")}
              busy={busy}
            />
          </div>

          {artefact.ruleFindings.length > 0 && (
            // The rule arm's own findings, kept whether or not the model arm ran (C2-3).
            <ul className="mt-3 space-y-1">
              {artefact.ruleFindings.map((finding) => (
                <li key={`${finding.ruleId}-${finding.subject}`} className="tp-den">
                  {finding.reason}
                </li>
              ))}
            </ul>
          )}

          {comparison && (
            <div className="mt-3 grid grid-cols-2 gap-3 sm:grid-cols-4">
              <Metric
                source={`both arms on the same screens and graph, code version ${snapshot.codeVersion}`}
                label="Both agree on"
                value={`${Math.round(comparison.agreementRate * 100)}%`}
              />
              <Metric source={`both arms on the same screens and graph, code version ${snapshot.codeVersion}`} label="Rule-based only" value={String(comparison.ruleOnly.length)} />
              <Metric source={`both arms on the same screens and graph, code version ${snapshot.codeVersion}`} label="AI model only" value={String(comparison.llmOnly.length)} />
              <Metric source={`both arms on the same screens and graph, code version ${snapshot.codeVersion}`} label="Conflicts" value={String(comparison.conflicts.length)} />
            </div>
          )}

          {conflicts.length > 0 && (
            <ul className="mt-3 space-y-1.5">
              {(allConflicts ? conflicts : conflicts.slice(0, CONFLICTS_SHOWN)).map((conflict, index) => (
                <li
                  key={`${conflict.endpointKey}-${conflict.field}-${index}`}
                  className="rounded-lg border border-[color:var(--tp-line)] px-3 py-2"
                >
                  <p className="tp-mono text-[11.5px] text-[color:var(--tp-ink)]">
                    {conflict.endpointKey} · {conflict.field}
                  </p>
                  <p className="tp-den mt-0.5">Rule-based: {conflict.ruleValue || "(empty)"}</p>
                  <p className="tp-den">AI model: {conflict.llmValue || "(empty)"}</p>
                </li>
              ))}
            </ul>
          )}
          {conflicts.length > CONFLICTS_SHOWN && (
            <button
              type="button"
              onClick={() => setAllConflicts((now) => !now)}
              className="mt-2 text-[12.5px] font-medium text-blue-700 hover:underline dark:text-blue-300"
            >
              {allConflicts ? "Show fewer" : `Show all ${conflicts.length} conflicts`}
            </button>
          )}
        </Panel>
      </StageSection>

      <StageSection id="contract-endpoints">
        <Panel
          label={`Endpoints (${artefact.contract.endpoints.length})`}
          action={
            <Button
              variant="outline"
              size="sm"
              busy={downloading}
              onClick={async () => {
                setDownloading(true);
                try {
                  await onDownloadOpenApi();
                } finally {
                  setDownloading(false);
                }
              }}
            >
              <Download className="h-3.5 w-3.5" />
              Download OpenAPI
            </Button>
          }
        >
          <ul className="space-y-2">
            {artefact.contract.endpoints.map((endpoint) => (
              <EndpointRow
                key={endpoint.id}
                endpoint={endpoint}
                onJumpToScreen={onJumpToScreen}
                onOpenRequirement={onOpenRequirement}
              />
            ))}
          </ul>
        </Panel>
      </StageSection>

      <StageSection id="contract-diff">
        <Panel label="Changes since the last version" icon={<GitCompare className="h-4 w-4" />}>
          {snapshot.diff ? (
            <>
              <p className="tp-den">
                Version {snapshot.diff.fromVersion} to {snapshot.diff.toVersion}
              </p>
              <div className="mt-2 grid grid-cols-3 gap-3">
                <Metric source={`the contract at version ${snapshot.diff.fromVersion} and at ${snapshot.diff.toVersion}`} label="Added" value={String(snapshot.diff.added.length)} />
                <Metric source={`the contract at version ${snapshot.diff.fromVersion} and at ${snapshot.diff.toVersion}`} label="Removed" value={String(snapshot.diff.removed.length)} />
                <Metric source={`the contract at version ${snapshot.diff.fromVersion} and at ${snapshot.diff.toVersion}`} label="Changed" value={String(snapshot.diff.changed.length)} />
              </div>
              {(snapshot.diff.added.length > 0 || snapshot.diff.removed.length > 0) && (
                <ul className="mt-3 space-y-1">
                  {snapshot.diff.added.map((id) => (
                    <li key={`added-${id}`} className="tp-mono text-[11.5px] text-emerald-700 dark:text-emerald-400">
                      + {id}
                    </li>
                  ))}
                  {snapshot.diff.removed.map((id) => (
                    <li key={`removed-${id}`} className="tp-mono text-[11.5px] text-red-600 dark:text-red-400">
                      - {id}
                    </li>
                  ))}
                </ul>
              )}
              {snapshot.diff.changed.length > 0 && (
                <ul className="mt-3 space-y-1.5">
                  {snapshot.diff.changed.map((change, index) => (
                    <li key={`${change.endpointId}-${change.field}-${index}`} className="tp-den">
                      <span className="tp-mono text-[color:var(--tp-ink)]">
                        {change.endpointId}
                      </span>
                      {`: ${change.field} was "${change.before || "(empty)"}", is now "${change.after || "(empty)"}"`}
                    </li>
                  ))}
                </ul>
              )}
            </>
          ) : (
            <Note>
              This is the first contract for this project, so there is nothing to compare it
              against yet. Change the scope or the method and this becomes the receipt for what
              moved.
            </Note>
          )}
        </Panel>
      </StageSection>
    </div>
  );
}

function ArmCard({
  name,
  blurb,
  endpoints,
  errors,
  attempts,
  chosen,
  available,
  failure,
  onChoose,
  busy,
}: {
  name: string;
  blurb: string;
  endpoints: number;
  errors: number;
  attempts: number;
  chosen: boolean;
  available: boolean;
  failure?: string | null;
  onChoose: () => void;
  busy: boolean;
}) {
  return (
    <div
      className={cn(
        "rounded-xl border px-3.5 py-3",
        chosen ? "border-blue-500/50 bg-blue-500/[0.05]" : "border-[color:var(--tp-line)]",
      )}
    >
      <div className="flex items-start justify-between gap-2">
        <p className="text-[13px] font-semibold text-[color:var(--tp-ink)]">{name}</p>
        {chosen ? (
          <Chip tone="info">Generating from this</Chip>
        ) : (
          <button
            type="button"
            disabled={busy || !available}
            onClick={onChoose}
            className="cursor-pointer rounded-lg border border-[color:var(--tp-line-strong)] px-2.5 py-1 text-[11.5px] font-medium text-[color:var(--tp-ink-2)] transition-colors hover:border-blue-500/50 hover:text-blue-600 disabled:cursor-default disabled:opacity-40"
          >
            Generate from this
          </button>
        )}
      </div>
      <p className="tp-den mt-1 leading-relaxed">{blurb}</p>
      {available ? (
        <p className="tp-den mt-2">
          {endpoints} endpoints · {errors} rule violation{errors === 1 ? "" : "s"} ·{" "}
          {attempts === 1 ? "first attempt" : `${attempts} attempts`}
        </p>
      ) : (
        <div className="mt-2 flex items-start gap-2 rounded-lg border border-amber-500/30 bg-amber-500/5 px-2.5 py-2">
          <AlertTriangle className="mt-0.5 h-3.5 w-3.5 shrink-0 text-amber-500" />
          <p className="tp-den">
            {failure ?? "This arm produced nothing."} The rule arm stands, which is why it
            is the one that always exists.
          </p>
        </div>
      )}
    </div>
  );
}

function EndpointRow({
  endpoint,
  onJumpToScreen,
  onOpenRequirement,
}: {
  endpoint: ApiEndpoint;
  onJumpToScreen: (screenId: string) => void;
  onOpenRequirement: (requirementId: string) => void;
}) {
  return (
    <li className="rounded-xl border border-[color:var(--tp-line)] px-3.5 py-3">
      <div className="flex flex-wrap items-baseline gap-2">
        <span className={cn("tp-mono text-[11.5px] font-semibold", METHOD_TONE[endpoint.method])}>
          {endpoint.method}
        </span>
        <span className="tp-mono text-[12.5px] text-[color:var(--tp-ink)]">{endpoint.path}</span>
        <span className="tp-den">{endpoint.summary}</span>
        <span className="tp-den ml-auto" title="Computed from how well this endpoint is grounded, never chosen by a model">
          {endpoint.confidence}% confidence
        </span>
      </div>

      <div className="mt-2 flex flex-wrap items-center gap-2">
        <span className="tp-den">
          {endpoint.authActors.length
            ? `${endpoint.authActors.join(", ")} may call this`
            : "unauthenticated"}
        </span>
        <TraceChips
          traces={endpoint.traces.requirementIds}
          onJump={onOpenRequirement}
          label="Traces to"
        />
        {endpoint.traces.storyIds.map((storyId) => (
          <span key={storyId} className="tp-mono rounded border border-[color:var(--tp-line)] px-1 py-px text-[10px]">
            {storyId}
          </span>
        ))}
        {endpoint.traces.screenIds.length > 0 ? (
          endpoint.traces.screenIds.map((screenId) => (
            <button
              key={screenId}
              type="button"
              onClick={() => onJumpToScreen(screenId)}
              title="The screen this endpoint was inferred from"
              className="tp-mono cursor-pointer rounded border border-blue-500/30 bg-blue-500/[0.07] px-1 py-px text-[10px] font-medium text-blue-600 transition-colors hover:border-blue-500/60 hover:underline dark:text-blue-300"
            >
              {screenId}
            </button>
          ))
        ) : (
          // Not hidden: an endpoint no screen grounds is exactly the one a
          // reader should look at twice before approving.
          <span className="tp-den">no screen evidence</span>
        )}
      </div>

      {endpoint.validation.length > 0 && (
        <ul className="mt-2 space-y-0.5">
          {endpoint.validation.map((rule) => (
            <li key={rule} className="tp-den">
              validates: {rule}
            </li>
          ))}
        </ul>
      )}
    </li>
  );
}

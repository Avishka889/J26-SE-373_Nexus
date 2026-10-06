import { FileText, ShieldX } from "lucide-react";
import { Chip, Expandable, Note, Panel } from "@/shared/ui/phase";
import { StageSection } from "@/shared/ui/stage";
import type { DeploySnapshot } from "../../api/types";
import { claimsSummary } from "../../model/claims";
import { EmptyNote, LevelChip, Mono, Quote } from "../bits";

/**
 * Changelog Analysis: what the release notes say, and what survived checking.
 *
 * The model extracts claims and a rule rates them, so a claim is shown only
 * because its quote was found in the notes, in the release window, and the
 * level beside it is the rule's. What the model itself thought the level was
 * is recorded and shown as that, never as the signal's vote.
 */
export function StageChangelog({ snapshot }: { snapshot: DeploySnapshot }) {
  const report = snapshot.changelog;
  if (!report) return <EmptyNote>No release notes have been read at this deploy version.</EmptyNote>;
  const packages = new Map((snapshot.updates?.updates ?? []).map((one) => [one.id, one]));
  const refused = report.perUpdate.flatMap((analysis) =>
    analysis.refused.map((claim) => ({ analysis, claim })),
  );

  return (
    <div className="space-y-4">
      <StageSection id="changelog-claims">
        <Panel
          icon={<FileText className="h-4 w-4 text-blue-400" />}
          label="Claims"
          title={`${report.claimsVerified} claims verified against the notes, ${report.claimsRefused} refused.`}
          // The prompt and the rule that rated the claims, for reproducing a
          // result, in a tooltip; the reader is told which model read the notes.
          meta={
            <span title={`Prompt ${report.promptId}; levels set by ${report.ruleId}`}>
              Read by {report.modelId}
            </span>
          }
        >
          <div className="space-y-5">
            {report.perUpdate.map((analysis) => {
              const update = packages.get(analysis.updateId);
              const call = analysis.model;
              return (
                <article key={analysis.updateId} className="min-w-0 space-y-2">
                  <header className="flex flex-wrap items-center gap-2">
                    <span className="break-words text-[13px] font-semibold text-[color:var(--tp-ink)]">
                      {update?.package ?? analysis.updateId}
                    </span>
                    {update && (
                      <span className="tp-den">
                        <Mono>{update.fromVersion}</Mono> to <Mono>{update.toVersion}</Mono>
                      </span>
                    )}
                    <LevelChip level={analysis.vote.level} title={analysis.vote.rationale} />
                  </header>
                  <Note className="text-[12.5px]">{analysis.vote.rationale}</Note>
                  {analysis.windows.length > 0 && (
                    <p className="tp-den break-words">Releases read: {analysis.windows.join(", ")}</p>
                  )}
                  {/* Closed until asked: one package's notes ran to 176 claims, and
                      the line above the list says what they are by kind. */}
                  {analysis.claims.length > 0 && (
                    <Expandable summary={claimsSummary(analysis.claims)}>
                      <div className="space-y-2">
                        {analysis.claims.map((claim) => (
                          <Quote
                            key={claim.id}
                            quote={claim.quote}
                            version={claim.version}
                            sourceUrl={claim.sourceUrl}
                            kind={claim.kind}
                          />
                        ))}
                      </div>
                    </Expandable>
                  )}
                  {call && (
                    <p className="tp-den break-words">
                      One call, {call.outcome}: {call.requests} request
                      {call.requests === 1 ? "" : "s"}, {call.promptTokens} tokens in and{" "}
                      {call.completionTokens} out.
                      {call.statedLevel
                        ? ` The model said ${call.statedLevel}; recorded for the study, used by nothing.`
                        : ""}
                    </p>
                  )}
                </article>
              );
            })}
          </div>
        </Panel>
      </StageSection>

      <StageSection id="changelog-refused">
        <Panel
          icon={<ShieldX className="h-4 w-4 text-blue-400" />}
          label="Refused claims"
          title="A claim whose quote is not in the notes, or sits outside the release window, is refused and counted."
        >
          {refused.length === 0 ? (
            <EmptyNote>No claim was refused: every quote the model gave is in the notes it was shown.</EmptyNote>
          ) : (
            <ul className="space-y-3">
              {refused.map(({ analysis, claim }, index) => (
                <li key={`${analysis.updateId}-${index}`} className="min-w-0">
                  <p className="flex flex-wrap items-center gap-2">
                    <span className="text-[13px] font-semibold">
                      {packages.get(analysis.updateId)?.package ?? analysis.updateId}
                    </span>
                    <Chip tone="caution">{claim.reason}</Chip>
                  </p>
                  {claim.quote && <p className="tp-prose mt-1 break-words">{claim.quote}</p>}
                  {claim.detail && <p className="tp-den mt-1 break-words">{claim.detail}</p>}
                </li>
              ))}
            </ul>
          )}
        </Panel>
      </StageSection>
    </div>
  );
}

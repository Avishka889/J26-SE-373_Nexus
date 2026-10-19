import { AlertTriangle, Gauge, Scale } from "lucide-react";
import { Expandable, Metric, Note, Panel } from "@/shared/ui/phase";
import { StageSection } from "@/shared/ui/stage";
import { claimsSummary } from "../../model/claims";
import type { DeploymentPageView, UpdateView } from "../../model/view";
import { EmptyNote, LevelChip, Mono, Quote, VoteChips } from "../bits";

const STRATEGY_WORDS: Record<string, string> = {
  automatic: "Ships automatically once released.",
  approval: "Ships once a developer approves it.",
  "approval-with-rollback":
    "Ships only after a developer reviews and approves it, with a rollback prepared.",
};

/**
 * One update, with everything a developer needs to act on it in one place
 * (NFR11): the level and who decided it, all three votes, the release note
 * sentences the changelog vote rests on, and the files the update reaches.
 */
export function UpdateCard({ update, compact = false }: { update: UpdateView; compact?: boolean }) {
  return (
    <article
      data-update-card={update.package}
      className="min-w-0 rounded-2xl border border-[color:var(--tp-line)] px-4 py-3.5"
    >
      <header className="flex flex-wrap items-start justify-between gap-x-3 gap-y-2">
        <div className="min-w-0 flex-1 basis-56">
          <p className="break-words text-[14px] font-semibold text-[color:var(--tp-ink)]">
            {update.package}
          </p>
          <p className="tp-den mt-0.5 break-words">
            <Mono>{update.from}</Mono> to <Mono>{update.to}</Mono>, a {update.change} change
          </p>
        </div>
        <span className="inline-flex flex-wrap items-center gap-2">
          <LevelChip level={update.level} />
          <span className="tp-den">
            decided by {update.decidedBy.length > 0 ? update.decidedBy.join(" and ") : "no signal"}
          </span>
        </span>
      </header>

      <div className="mt-2">
        <VoteChips votes={update.votes} />
      </div>

      {update.advisory && (
        <p className="mt-3 flex items-start gap-2 rounded-xl border border-amber-500/30 bg-amber-500/5 px-3 py-2 text-[12.5px] text-[color:var(--tp-ink)]">
          <AlertTriangle className="mt-0.5 h-3.5 w-3.5 shrink-0 text-amber-500" />
          <span className="min-w-0 break-words">{update.advisory}</span>
        </p>
      )}

      <div className="mt-3 grid grid-cols-1 gap-4 lg:grid-cols-2">
        <div className="min-w-0">
          <p className="tp-label">What the release notes say</p>
          <div className="mt-2 space-y-2">
            {update.quotes.length > 0 ? (
              compact ? (
                update.quotes
                  .slice(0, 2)
                  .map((claim) => (
                    <Quote
                      key={claim.id}
                      quote={claim.quote}
                      version={claim.version}
                      sourceUrl={claim.sourceUrl}
                      kind={claim.kind}
                    />
                  ))
              ) : (
                // Closed until asked, the summary saying what the claims are by
                // kind, so the evidence for the level stays beside it (NFR11).
                <Expandable summary={claimsSummary(update.quotes)}>
                  <div className="space-y-2">
                    {update.quotes.map((claim) => (
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
              )
            ) : (
              <Note className="text-[12.5px]">
                {update.votes.find((vote) => vote.signal === "changelog")?.abstained ||
                  "No verified claim is cited."}
              </Note>
            )}
          </div>
        </div>
        <div className="min-w-0">
          <p className="tp-label">Where the project uses it</p>
          <div className="mt-2">
            {update.files.length > 0 ? (
              <ul className="space-y-1">
                {update.files.map((file) => (
                  <li key={file}>
                    <Mono>{file}</Mono>
                  </li>
                ))}
              </ul>
            ) : (
              <Note className="text-[12.5px]">
                No file in this project uses a symbol this update changes.
                {update.usage
                  ? ` The package is ${update.usage.importsPackage ? "imported" : "not imported"}, and ${update.usage.changedSymbols} changed symbol${update.usage.changedSymbols === 1 ? " is" : "s are"} known.`
                  : ""}
              </Note>
            )}
          </div>
        </div>
      </div>

      <p className="mt-3 text-[12.5px] text-[color:var(--tp-ink)]">{STRATEGY_WORDS[update.strategy]}</p>
      {!compact &&
        (update.explanationSource === "model" ? (
          <div className="mt-2">
            <p className="tp-label">Explained by the model, checked against the evidence</p>
            <Note className="mt-1 text-[12.5px]">{update.explanation}</Note>
          </div>
        ) : (
          // A rule written summary says what this card already shows, so it is
          // not shown twice; only the reason there is no model's is.
          update.explanationNote && (
            <p className="tp-den mt-2">No model explanation: {update.explanationNote}.</p>
          )
        ))}
    </article>
  );
}

/**
 * Risk Assessment: three signals per update and the most cautious of them.
 *
 * The final level is the rule's (safety-first-max/1), recomputed by the
 * contract on every read, so nothing on this page can show a level the rule
 * did not produce. Where the signals disagree, the page says so beside the
 * level rather than averaging it away.
 */
export function StageRisk({
  view,
  version,
}: {
  view: DeploymentPageView;
  version: number;
}) {
  if (view.updates.length === 0) {
    return <EmptyNote>No update has been assessed at this deploy version.</EmptyNote>;
  }
  const disagreeing = view.updates.filter((one) => one.disagreement);
  const source = `risk report at deploy version ${version}, rule safety-first-max/1`;

  return (
    <div className="space-y-4">
      <StageSection id="risk-levels">
        <Panel
          icon={<Gauge className="h-4 w-4 text-blue-400" />}
          label="By risk level"
          title="How each update may ship: Low automatically, Medium on approval, High on review with a rollback prepared."
          meta={`Source: ${source}`}
        >
          <div className="grid grid-cols-3 gap-4">
            <Metric source={source} label="High" value={view.levels.high} tone={view.levels.high > 0 ? "fail" : "muted"} note="review and rollback" />
            <Metric source={source} label="Medium" value={view.levels.medium} tone={view.levels.medium > 0 ? "caution" : "muted"} note="approval" />
            <Metric source={source} label="Low" value={view.levels.low} tone="pass" note="automatic" />
          </div>
        </Panel>
      </StageSection>

      <StageSection id="risk-updates">
        <Panel
          icon={<Scale className="h-4 w-4 text-blue-400" />}
          label="Updates and evidence"
          title="Every update with its level, its votes, the release note sentences and the files, together."
        >
          <div className="space-y-3">
            {view.updates.map((update) => (
              <UpdateCard key={update.updateId} update={update} />
            ))}
          </div>
        </Panel>
      </StageSection>

      <StageSection id="risk-disagreements">
        <Panel
          icon={<AlertTriangle className="h-4 w-4 text-blue-400" />}
          label="Where signals disagree"
          title="The most cautious level was taken in each case; a developer should confirm it."
        >
          {disagreeing.length === 0 ? (
            <EmptyNote>The signals that voted agree on every update.</EmptyNote>
          ) : (
            <ul className="space-y-3">
              {disagreeing.map((update) => (
                <li key={update.updateId} className="min-w-0">
                  <p className="flex flex-wrap items-center gap-2">
                    <span className="text-[13px] font-semibold">{update.package}</span>
                    <LevelChip level={update.level} />
                  </p>
                  <Note className="mt-1 break-words text-[12.5px]">{update.advisory}</Note>
                </li>
              ))}
            </ul>
          )}
        </Panel>
      </StageSection>
    </div>
  );
}

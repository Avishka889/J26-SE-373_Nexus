import { AlertTriangle, Check } from "lucide-react";
import { cn } from "@/shared/utils/cn";
import { Metric, Note, Panel } from "@/shared/ui/phase";
import { StageSection } from "@/shared/ui/stage";
import type { CodeSnapshot } from "../../api/types";

/**
 * The stack, scored by arithmetic and chosen by a person.
 *
 * Every number here is a sum over counted facts from the design, and the
 * breakdown is shown rather than summarised so a reader can check it. The
 * explanation is the only model written part, and it is guarded against
 * citing figures the design does not contain.
 *
 * A stack the platform cannot generate yet says so, with the reason, instead
 * of being hidden. Hiding it would make the shortlist look like a judgement
 * when it is partly an inventory.
 */
export function StageTechStack({
  snapshot,
  onSelect,
  busy,
}: {
  snapshot: CodeSnapshot;
  onSelect: (stackId: string) => void;
  busy: boolean;
}) {
  const stack = snapshot.techStack;
  if (!stack) return null;
  // "Recommended" sat on a stack that cannot be generated yet, beside a Select
  // that only another stack had. The scoring's top stack keeps its place as the
  // highest score; the recommendation is the best one that can be built.
  const top = stack.candidates.find((candidate) => candidate.id === stack.recommendedId);
  const recommendedId = top?.available
    ? top.id
    : [...stack.candidates]
        .filter((candidate) => candidate.available)
        .sort((a, b) => b.score - a.score)[0]?.id;

  return (
    <div className="space-y-5">
      <StageSection id="stack-facts">
        <Panel label="What the scoring read" title="Counted from the design, not estimated.">
          <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
            {stack.facts.map((fact) => (
              <Metric
                key={fact.label}
                label={fact.label}
                value={String(fact.value)}
                source={`counted from design version ${snapshot.generatedFromDesignVersion}`}
              />
            ))}
          </div>
        </Panel>
      </StageSection>

      <StageSection id="stack-candidates">
        <Panel label="Candidates">
          <div className="space-y-3">
            {stack.candidates.map((candidate) => {
              const selected = stack.selectedId === candidate.id;
              return (
                <div
                  key={candidate.id}
                  className={cn(
                    "rounded-xl border px-3.5 py-3",
                    selected
                      ? "border-blue-500/50 bg-blue-500/[0.05]"
                      : "border-[color:var(--tp-line)]",
                  )}
                >
                  <div className="flex flex-wrap items-start justify-between gap-3">
                    <div className="min-w-0">
                      <p className="text-[13.5px] font-semibold text-[color:var(--tp-ink)]">
                        {candidate.name}
                        {recommendedId === candidate.id && (
                          <span className="tp-den ml-2">recommended</span>
                        )}
                        {stack.recommendedId === candidate.id && !candidate.available && (
                          <span className="tp-den ml-2">highest score</span>
                        )}
                      </p>
                      <p className="tp-den mt-0.5">
                        {candidate.layers
                          .map((layer) => `${layer.choice}${layer.version ? ` ${layer.version}` : ""}`)
                          .join(" · ")}
                      </p>
                    </div>
                    <div className="flex shrink-0 items-center gap-3">
                      <span className="tp-mono text-[13px] font-semibold text-[color:var(--tp-ink)]">
                        {candidate.score}
                      </span>
                      {candidate.available ? (
                        <button
                          type="button"
                          disabled={busy || selected}
                          onClick={() => onSelect(candidate.id)}
                          // Named for its stack: every one was "Select".
                          aria-label={selected ? `${candidate.name}, selected` : `Select ${candidate.name}`}
                          className={cn(
                            "rounded-lg border px-3 py-1.5 text-[12px] font-medium transition-colors disabled:opacity-50",
                            selected
                              ? "cursor-default border-blue-500/50 text-blue-600 dark:text-blue-300"
                              : "cursor-pointer border-[color:var(--tp-line-strong)] text-[color:var(--tp-ink-2)] hover:border-blue-500/50 hover:text-blue-600",
                          )}
                        >
                          {selected ? (
                            <span className="flex items-center gap-1.5">
                              <Check className="h-3.5 w-3.5" />
                              Selected
                            </span>
                          ) : (
                            "Select"
                          )}
                        </button>
                      ) : (
                        <span className="flex items-center gap-1.5 rounded-lg border border-amber-500/30 bg-amber-500/5 px-2.5 py-1.5 text-[11.5px] font-medium text-amber-700 dark:text-amber-400">
                          <AlertTriangle className="h-3.5 w-3.5" />
                          Not generatable yet
                        </span>
                      )}
                    </div>
                  </div>

                  {candidate.unavailableReason && (
                    <Note className="mt-2">{candidate.unavailableReason}</Note>
                  )}
                  {candidate.explanation && (
                    <p className="tp-den mt-2 leading-relaxed">{candidate.explanation}</p>
                  )}

                  <ul className="mt-2.5 flex flex-wrap gap-x-4 gap-y-1">
                    {candidate.scoreBreakdown.map((part, index) => (
                      <li key={`${part.label}-${index}`} className="tp-den">
                        <span className="tp-mono mr-1.5 text-[color:var(--tp-ink-2)]">
                          {part.points >= 0 ? `+${part.points}` : part.points}
                        </span>
                        {part.label}
                      </li>
                    ))}
                  </ul>
                </div>
              );
            })}
          </div>
          <Note className="mt-3">
            Choosing a stack records the decision and costs no run: the generators build
            the MERN stack whatever is selected today, so regenerating would spend a run to
            produce identical code. When a second stack's generators land, this becomes a
            change that regenerates, and this note goes with it.
          </Note>
        </Panel>
      </StageSection>
    </div>
  );
}

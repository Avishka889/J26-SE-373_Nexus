import { Check, Info, Minus, Plus } from "lucide-react";
import { cn } from "@/shared/utils/cn";
import { StageSection } from "@/shared/ui/stage";
import { Button } from "@/shared/ui/primitives";
import { Bar, Chip, Hairline, Note, Panel } from "@/shared/ui/phase";
import type { ArchitectureRecommendation } from "../../api/types";
import { formatWhen } from "@/shared/utils/time";

/**
 * Candidates are deployment shapes, so they can be compared with each other, and
 * each one states its cons as well as its pros. A code organisation style is a
 * different question and appears as a note, not as a card scored against them.
 */
export function StageArchitectureChoice({
  architecture,
  reviewer,
  onSelect,
  isSelecting,
}: {
  architecture: ArchitectureRecommendation | null;
  reviewer: string;
  /** May resolve when the server has answered, which keeps that candidate's button busy. */
  onSelect: (candidateId: string) => void | Promise<unknown>;
  isSelecting: boolean;
}) {
  // A leaf stage is allowed to fail without taking the run down, so the phase can
  // reach the gate with no recommendation at all. Saying so is the honest answer;
  // reading through it crashed the whole page behind the error boundary.
  if (!architecture) {
    return (
      <Panel
        label="No shapes were scored"
        title="The recommendation did not finish, so there is nothing to choose between yet."
      >
        <Note>
          Nothing was scored for this version. Retry the Architecture Recommendation stage, and the
          shapes and their trade-offs appear here.
        </Note>
      </Panel>
    );
  }

  const selectedId = architecture.selectedCandidateId;

  return (
    <div className="space-y-5">
      <StageSection id="architecture-candidates">
        <Panel
          label="Choose the shape this system is built in"
          title="Scored against the parsed scope and constraints. The recommendation is a starting point, not the decision."
          meta={
            selectedId
              ? `Selected by ${architecture.selectedBy ?? reviewer} at ${formatWhen(architecture.selectedAt)}`
              : "Nothing selected yet"
          }
        >
          <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
            {architecture.candidates.map((candidate) => {
              const selected = candidate.id === selectedId;
              const recommended = candidate.id === architecture.recommendedCandidateId;

              return (
                <div
                  key={candidate.id}
                  className={cn(
                    "flex flex-col rounded-2xl border px-4 py-4 transition-colors",
                    selected
                      ? "border-blue-500/60 bg-blue-500/[0.05]"
                      : "border-[color:var(--tp-line)]",
                  )}
                >
                  <div className="flex flex-wrap items-start justify-between gap-2">
                    <div className="min-w-0">
                      <p className="text-[15px] font-semibold text-[color:var(--tp-ink)]">
                        {candidate.name}
                      </p>
                      <div className="mt-1 flex flex-wrap items-center gap-1.5">
                        {recommended && <Chip tone="info">Recommended</Chip>}
                        {selected && (
                          <Chip tone="pass" icon={<Check className="h-3 w-3" />}>
                            Selected
                          </Chip>
                        )}
                      </div>
                    </div>
                    <div className="shrink-0 text-right">
                      <p className="tp-num text-2xl">{candidate.score}</p>
                      <p className="tp-den">out of 100</p>
                    </div>
                  </div>

                  <Bar value={candidate.score} tone={selected ? "ink" : "muted"} className="mt-3" />

                  <p className="tp-prose mt-3">{candidate.rationale}</p>

                  <div className="mt-3.5 grid grid-cols-1 gap-3 sm:grid-cols-2">
                    <div>
                      <p className="tp-label">What it gives you</p>
                      <ul className="mt-1.5 space-y-1">
                        {candidate.pros.map((pro) => (
                          <li key={pro} className="flex items-start gap-1.5 text-[12px] leading-relaxed">
                            <Plus className="mt-0.5 h-3 w-3 shrink-0 text-[color:var(--tp-pass)]" />
                            <span className="text-[color:var(--tp-ink-2)]">{pro}</span>
                          </li>
                        ))}
                      </ul>
                    </div>
                    <div>
                      <p className="tp-label">What it costs you</p>
                      <ul className="mt-1.5 space-y-1">
                        {candidate.cons.map((con) => (
                          <li key={con} className="flex items-start gap-1.5 text-[12px] leading-relaxed">
                            <Minus className="mt-0.5 h-3 w-3 shrink-0 text-[color:var(--tp-caution)]" />
                            <span className="text-[color:var(--tp-ink-2)]">{con}</span>
                          </li>
                        ))}
                      </ul>
                    </div>
                  </div>

                  <div className="mt-auto pt-4">
                    <Button
                      variant={selected ? "outline" : "primary"}
                      size="sm"
                      disabled={selected || isSelecting}
                      onClick={() => onSelect(candidate.id)}
                    >
                      {selected ? (
                        <>
                          <Check className="h-3.5 w-3.5" />
                          Selected
                        </>
                      ) : (
                        `Select ${candidate.name}`
                      )}
                    </Button>
                  </div>
                </div>
              );
            })}
          </div>

          <Hairline className="my-4" />

          <div className="flex items-start gap-2.5 rounded-xl border border-[color:var(--tp-line)] bg-[color:var(--tp-surface-2)] px-3.5 py-3">
            <Info className="mt-0.5 h-4 w-4 shrink-0 text-[color:var(--tp-muted)]" />
            <div className="min-w-0">
              <p className="text-[13px] font-medium text-[color:var(--tp-ink)]">
                {architecture.style.name}
              </p>
              <Note className="mt-1">{architecture.style.note}</Note>
            </div>
          </div>
        </Panel>
      </StageSection>

      <StageSection id="architecture-style">
        <Panel label="What this decides, and what it does not">
          <Note>
            This picks the shape the system is deployed in. It does not pick the languages, frameworks
            or libraries: those are proposed and chosen in Code Generation, against the shape you settle
            on here.
          </Note>
        </Panel>
      </StageSection>
    </div>
  );
}

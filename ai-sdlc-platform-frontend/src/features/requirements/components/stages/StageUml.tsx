import { useMemo, useState } from "react";
import { Check, Code2, Copy, Maximize2, Shapes } from "lucide-react";
import { cn } from "@/shared/utils/cn";
import { StageSection, TraceChips } from "@/shared/ui/stage";
import { Button, CodeBlock } from "@/shared/ui/primitives";
import { Chip, Note, Panel } from "@/shared/ui/phase";
import { MermaidDiagram } from "@/shared/viz";
import { UmlDiagramModal } from "../uml/UmlDiagramModal";
import type { DesignSnapshot, UmlDiagram } from "../../api/types";
import type { DomainModel } from "../../model/domain";
import {
  buildClassDiagram,
  buildErDiagram,
  buildSequenceDiagram,
} from "../../model/mermaid";

/**
 * Class and entity relationship sources are generated from the graph projection.
 * Sequence sources keep their authored steps but resolve every name from the
 * graph, so a rename propagates without flattening the interaction.
 */
export function StageUml({
  snapshot,
  domain,
  projectName,
  isDark,
  onJump,
}: {
  snapshot: DesignSnapshot;
  domain: DomainModel;
  /** Named in a saved diagram's filename. */
  projectName: string;
  isDark: boolean;
  onJump: (requirementId: string) => void;
}) {
  const [useCaseId, setUseCaseId] = useState(
    snapshot.uml.useCases[0]?.id ?? "",
  );

  const sourceFor = useMemo(() => {
    const useCase =
      snapshot.uml.useCases.find((u) => u.id === useCaseId) ??
      snapshot.uml.useCases[0];
    return (diagram: UmlDiagram): string => {
      if (diagram.source) return diagram.source;
      if (diagram.kind === "class") return buildClassDiagram(domain);
      if (diagram.kind === "er") return buildErDiagram(domain);
      if (diagram.kind === "sequence" && useCase)
        return buildSequenceDiagram(useCase, domain);
      return "";
    };
  }, [domain, snapshot.uml.useCases, useCaseId]);

  // Which kinds describe behaviour. Everything else is structure, so a kind
  // added later lands in one of the two sections rather than in neither.
  const behavioural = snapshot.uml.diagrams.filter(
    (d) => d.kind === "sequence" || d.kind === "activity",
  );
  const structural = snapshot.uml.diagrams.filter(
    (d) => d.kind !== "sequence" && d.kind !== "activity",
  );

  const renderCard = (diagram: UmlDiagram) => (
    <DiagramCard
      key={diagram.id}
      diagram={diagram}
      source={sourceFor(diagram)}
      isDark={isDark}
      onJump={onJump}
      projectName={projectName}
      version={snapshot.stages["uml-diagrams"].generatedFromVersion}
      useCaseSelector={
        diagram.kind === "sequence" ? (
          <select
            value={useCaseId}
            onChange={(e) => setUseCaseId(e.target.value)}
            aria-label="Which interaction to show"
            className="rounded-lg border border-[color:var(--tp-line)] bg-transparent px-2 py-1 text-[12px] outline-none focus:border-blue-500/50"
          >
            {snapshot.uml.useCases.map((useCase) => (
              <option key={useCase.id} value={useCase.id}>
                {useCase.name}
              </option>
            ))}
          </select>
        ) : null
      }
      extraTraces={
        diagram.kind === "sequence"
          ? (snapshot.uml.useCases.find((u) => u.id === useCaseId)?.traces ??
            [])
          : []
      }
      storyId={
        diagram.kind === "sequence"
          ? (snapshot.uml.useCases.find((u) => u.id === useCaseId)?.storyId ??
            null)
          : null
      }
    />
  );

  return (
    <div className="space-y-5">
      {/* Split by what the anchors above actually name. One grid holding every
          diagram meant the Behaviour pill scrolled to the top of a section whose
          first card is the class diagram, so the sequence diagram never came
          into view and the spy lit Structure again. */}
      <StageSection id="uml-structure" className="space-y-5">
        <Panel
          icon={<Shapes className="h-4 w-4" />}
          label="Four views of the same design"
          title="Nothing here is drawn by hand: each diagram is built from the architecture graph, so they cannot disagree with it or with each other."
        />
        <div className="grid grid-cols-1 items-start gap-5 xl:grid-cols-2">
          {structural.map(renderCard)}
        </div>
      </StageSection>

      <StageSection
        id="uml-behaviour"
        className="grid grid-cols-1 items-start gap-5 xl:grid-cols-2"
      >
        {behavioural.map(renderCard)}
      </StageSection>
    </div>
  );
}

function DiagramCard({
  diagram,
  source,
  isDark,
  onJump,
  projectName,
  version,
  useCaseSelector,
  extraTraces,
  storyId,
}: {
  diagram: UmlDiagram;
  source: string;
  isDark: boolean;
  onJump: (requirementId: string) => void;
  projectName: string;
  version: number;
  useCaseSelector: React.ReactNode;
  extraTraces: string[];
  storyId: string | null;
}) {
  const [mode, setMode] = useState<"diagram" | "source">("diagram");
  // A card is a preview. Reading a class diagram of thirty entities needs room,
  // and taking it away from the reader is the whole point of the control.
  const [expanded, setExpanded] = useState(false);
  const [copied, setCopied] = useState(false);

  const traces = Array.from(new Set([...diagram.traces, ...extraTraces]));

  const copy = async () => {
    await navigator.clipboard.writeText(source);
    setCopied(true);
    window.setTimeout(() => setCopied(false), 1600);
  };

  return (
    <Panel
      label={diagram.title}
      title={diagram.description}
      action={
        <div className="flex flex-wrap items-center gap-2">
          {useCaseSelector}
          <div className="flex overflow-hidden rounded-lg border border-[color:var(--tp-line)]">
            {(["diagram", "source"] as const).map((value) => (
              <button
                key={value}
                type="button"
                onClick={() => setMode(value)}
                aria-pressed={mode === value}
                className={cn(
                  "px-2.5 py-1 text-[11px] font-medium capitalize transition-colors",
                  mode === value
                    ? "bg-blue-500/10 text-blue-600 dark:text-blue-300"
                    : "text-[color:var(--tp-muted)]",
                )}
              >
                {value}
              </button>
            ))}
          </div>
          {mode === "diagram" && (
            <button
              type="button"
              onClick={() => setExpanded(true)}
              aria-label={`Open ${diagram.title} larger`}
              title="Open larger"
              className="flex h-[26px] w-[26px] items-center justify-center rounded-lg border border-[color:var(--tp-line)] text-[color:var(--tp-muted)] transition-colors hover:border-blue-500/50 hover:text-blue-600"
            >
              <Maximize2 className="h-3.5 w-3.5" />
            </button>
          )}
        </div>
      }
    >
      {expanded && (
        <UmlDiagramModal
          diagram={diagram}
          source={source}
          projectName={projectName}
          version={version}
          isDark={isDark}
          onClose={() => setExpanded(false)}
        />
      )}
      {mode === "diagram" ? (
        <MermaidDiagram
          chart={source}
          id={`${diagram.id}-${source.length}`}
          isDark={isDark}
          minHeight={280}
        />
      ) : (
        <div>
          <div className="mb-2 flex justify-end">
            <Button size="sm" variant="outline" onClick={copy}>
              {copied ? (
                <Check className="h-3.5 w-3.5" />
              ) : (
                <Copy className="h-3.5 w-3.5" />
              )}
              {copied ? "Copied" : "Copy source"}
            </Button>
          </div>
          <CodeBlock code={source} language="mermaid" className="max-h-72" />
        </div>
      )}

      <div className="mt-3 flex flex-wrap items-center gap-2">
        {diagram.source === null && (
          <Chip
            tone="info"
            icon={<Code2 className="h-3 w-3" />}
            title="Built from the architecture graph"
          >
            Generated from the graph
          </Chip>
        )}
        {storyId && <Chip>{storyId}</Chip>}
        <TraceChips traces={traces} onJump={onJump} />
      </div>

      {diagram.kind === "sequence" && (
        <Note className="mt-2.5">
          The steps are authored, so the interaction keeps its real shape. Every
          name in them is read from the graph, so renaming a node changes this
          diagram too.
        </Note>
      )}
    </Panel>
  );
}

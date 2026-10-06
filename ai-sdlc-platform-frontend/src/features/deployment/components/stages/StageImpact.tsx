import { FileSearch, Network, Unlink } from "lucide-react";
import { Chip, Note, Panel } from "@/shared/ui/phase";
import { StageSection, TraceChips } from "@/shared/ui/stage";
import type { DeploySnapshot } from "../../api/types";
import { EmptyNote, LevelChip, Mono } from "../bits";

/**
 * Impact Analysis: where this project uses what each update changes.
 *
 * Files come only from references that were re-read and found where the
 * index said they were, and each file is mapped to Semantic Architecture Graph
 * nodes through the evidence that links them. A file that maps to nothing is
 * listed as unmapped rather than assigned a guess. When no file uses a changed
 * symbol, the stage says that, update by update, with what the usage signal
 * actually found.
 */
export function StageImpact({
  snapshot,
  onJump,
}: {
  snapshot: DeploySnapshot;
  onJump: (requirementId: string) => void;
}) {
  const impact = snapshot.impact;
  if (!impact) return <EmptyNote>The project's code has not been read at this deploy version.</EmptyNote>;
  const packages = new Map((snapshot.updates?.updates ?? []).map((one) => [one.id, one.package]));
  const changed = new Map<string, number>();
  for (const symbol of impact.changedSymbols) {
    changed.set(symbol.updateId, (changed.get(symbol.updateId) ?? 0) + 1);
  }
  const granularity =
    impact.granularity === "module"
      ? "Maven modules, because this project has no Semantic Architecture Graph"
      : "Semantic Architecture Graph nodes";

  return (
    <div className="space-y-4">
      <StageSection id="impact-components">
        <Panel
          icon={<Network className="h-4 w-4 text-blue-400" />}
          label="Affected components"
          title={`Mapped to ${granularity}.`}
          meta={`${impact.extraction.filesIndexed} files indexed by ${impact.extraction.parser} in ${impact.extraction.seconds.toFixed(1)} s`}
        >
          {impact.affectedComponents.length === 0 ? (
            <EmptyNote>
              No component is reached: no file in this project references a symbol these updates
              change.
            </EmptyNote>
          ) : (
            <ul className="space-y-3">
              {impact.affectedComponents.map((component) => (
                <li key={component.nodeId} className="min-w-0">
                  <p className="flex flex-wrap items-center gap-2">
                    <span className="break-words text-[13px] font-semibold">{component.label}</span>
                    <Chip>{component.kind}</Chip>
                    <TraceChips traces={component.traces} onJump={onJump} />
                  </p>
                  <ul className="mt-1 space-y-0.5">
                    {component.links.map((link) => (
                      <li key={`${link.path}-${link.via}`} className="tp-den break-words">
                        <Mono>{link.path}</Mono> via {link.via}: {link.detail}
                      </li>
                    ))}
                  </ul>
                </li>
              ))}
            </ul>
          )}
        </Panel>
      </StageSection>

      <StageSection id="impact-files">
        <Panel
          icon={<FileSearch className="h-4 w-4 text-blue-400" />}
          label="Affected files"
          title="Each file holds at least one checked reference to a changed symbol."
        >
          {impact.affectedFiles.length > 0 ? (
            <ul className="mb-4 space-y-1.5">
              {impact.affectedFiles.map((file) => (
                <li key={file.path} className="flex flex-wrap items-center gap-2">
                  <Mono>{file.path}</Mono>
                  <Chip>{file.referenceCount} references</Chip>
                </li>
              ))}
            </ul>
          ) : (
            <EmptyNote>No file in this project uses a symbol these updates change.</EmptyNote>
          )}
          <p className="tp-label mt-4">What the usage signal found, update by update</p>
          <ul className="mt-2 divide-y divide-[color:var(--tp-line)]">
            {impact.perUpdate.map((one) => (
              <li key={one.updateId} className="py-2.5">
                <p className="flex flex-wrap items-center gap-2">
                  <span className="break-words text-[13px] font-semibold">
                    {packages.get(one.updateId) ?? one.updateId}
                  </span>
                  <LevelChip level={one.vote.level} />
                  <Chip>{one.importsPackage ? "imported by the code" : "not imported"}</Chip>
                  <Chip>{changed.get(one.updateId) ?? 0} changed symbols known</Chip>
                </p>
                <Note className="mt-1 break-words text-[12.5px]">
                  {one.vote.level ? one.vote.rationale : one.vote.abstainedReason}
                </Note>
                <p className="tp-den mt-1 break-words">
                  API diff {one.apiDiff}: {one.apiDiffReason}
                </p>
              </li>
            ))}
          </ul>
        </Panel>
      </StageSection>

      <StageSection id="impact-unmapped">
        <Panel
          icon={<Unlink className="h-4 w-4 text-blue-400" />}
          label="Not mapped"
          title="Files that reach no component, and references that could not be checked."
        >
          {impact.unmappedFiles.length === 0 && impact.refusedReferences.length === 0 ? (
            <EmptyNote>Nothing unmapped and nothing refused.</EmptyNote>
          ) : (
            <ul className="space-y-2">
              {impact.unmappedFiles.map((file) => (
                <li key={file.path} className="break-words text-[13px]">
                  <Mono>{file.path}</Mono> <Chip tone="caution">{file.reason}</Chip>{" "}
                  <span className="tp-den">{file.detail}</span>
                </li>
              ))}
              {impact.refusedReferences.map((ref) => (
                <li key={`${ref.path}:${ref.line}`} className="break-words text-[13px]">
                  <Mono>
                    {ref.path}:{ref.line}
                  </Mono>{" "}
                  <Chip tone="caution">{ref.reason}</Chip> <span className="tp-den">{ref.detail}</span>
                </li>
              ))}
            </ul>
          )}
        </Panel>
      </StageSection>
    </div>
  );
}

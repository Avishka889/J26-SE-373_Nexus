import { FileCode2, LayoutTemplate, ListChecks } from "lucide-react";
import { Chip, Note, Panel } from "@/shared/ui/phase";
import { StageSection } from "@/shared/ui/stage";
import type { DeploySnapshot } from "../../api/types";
import { EmptyNote, Facts, Mono, StateChip } from "../bits";
import { PipelineStudio } from "./PipelineStudio";

/**
 * CI/CD Pipeline: what was generated, from which template, and what checked it.
 *
 * Validity is computed from one generation, never from a repaired one (NFR5),
 * and a validator that could not run says `not-run` with its reason rather
 * than passing by default. A stack no template fits is reported, not given a
 * configuration nobody validated (FR14).
 */
export function StagePipeline({ snapshot }: { snapshot: DeploySnapshot }) {
  const pipeline = snapshot.pipeline;
  if (!pipeline) return <EmptyNote>No deployment files have been generated at this deploy version.</EmptyNote>;
  const layout = pipeline.stack.layout;

  return (
    <div className="space-y-4">
      <StageSection id="pipeline-layout">
        <Panel
          icon={<LayoutTemplate className="h-4 w-4 text-blue-400" />}
          label="Detected layout"
          title="Read from the project's own files, which is what decides the templates."
        >
          {!pipeline.stack.supported ? (
            <EmptyNote>
              {pipeline.stack.stackId} is not supported: {pipeline.stack.reason}
            </EmptyNote>
          ) : (
            <>
              <Facts
                rows={[
                  ["Stack", pipeline.stack.stackId],
                  ["Layout", layout?.kind ?? "unknown"],
                  ["Frontend", layout?.frontendDir ? <Mono>{layout.frontendDir}</Mono> : "none"],
                  ["Backend", layout?.backendDir ? <Mono>{layout.backendDir}</Mono> : "none"],
                  [
                    "Served by",
                    layout?.servesFrontendFromBackend
                      ? "the backend, one process on one port"
                      : "separate hosts",
                  ],
                  ["Kubernetes", pipeline.kubernetes ? "manifests generated" : pipeline.kubernetesReason],
                ]}
              />
              {layout && layout.evidence.length > 0 && (
                <ul className="mt-3 space-y-1">
                  {layout.evidence.map((line) => (
                    <li key={line} className="tp-den break-words">
                      {line}
                    </li>
                  ))}
                </ul>
              )}
            </>
          )}
        </Panel>
      </StageSection>

      <StageSection id="pipeline-files">
        <Panel
          icon={<FileCode2 className="h-4 w-4 text-blue-400" />}
          label="Generated files"
          title={`${pipeline.files.length} files, committed on top of the generated code at release.`}
          meta={`Candidate ${pipeline.candidateHash.slice(0, 12)}`}
        >
          <PipelineStudio
            projectId={snapshot.projectId}
            version={pipeline.version}
            files={pipeline.files}
          />
        </Panel>
      </StageSection>

      <StageSection id="pipeline-validation">
        <Panel
          icon={<ListChecks className="h-4 w-4 text-blue-400" />}
          label="Validation"
          title={
            pipeline.valid
              ? "Every file passed every validator that applies to it, on first generation."
              : "At least one file failed a validator; nothing was repaired after the fact."
          }
        >
          <ul className="space-y-3">
            {pipeline.files.map((file) => (
              <li key={file.path} className="min-w-0">
                <p className="flex flex-wrap items-center gap-2">
                  <Mono>{file.path}</Mono>
                  <StateChip state={file.valid ? "passed" : "failed"} />
                </p>
                <ul className="mt-1 flex flex-wrap gap-1.5">
                  {file.validations.map((check) => (
                    <li key={check.validator}>
                      <Chip
                        tone={check.outcome === "passed" ? "pass" : check.outcome === "failed" ? "fail" : "neutral"}
                        title={[check.tool, check.reason, ...check.findings].filter(Boolean).join(" ")}
                      >
                        {check.validator}: {check.outcome}
                      </Chip>
                    </li>
                  ))}
                </ul>
                {file.validations
                  .filter((check) => check.findings.length > 0 || (check.outcome !== "passed" && check.reason))
                  .map((check) => (
                    <Note key={check.validator} className="mt-1 break-words text-[12.5px]">
                      {check.validator}: {check.findings.join("; ") || check.reason}
                    </Note>
                  ))}
              </li>
            ))}
          </ul>
        </Panel>
      </StageSection>
    </div>
  );
}

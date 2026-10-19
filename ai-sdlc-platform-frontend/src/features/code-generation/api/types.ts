/**
 * The C2 display contract, re-exported from the generated package.
 *
 * `@sdlc/contracts-ts` is generated from the committed JSON Schemas, which are
 * generated from the Pydantic models: one author, two derived artefacts. The
 * design phase learned this the expensive way, by hand maintaining a copy of
 * every interface behind a CI test that compared field names and could never
 * see a nullability difference. This phase starts where that one ended up.
 *
 * Two kinds of declaration are hand written and only two: `Stages`, because
 * the generator emits an index signature where the server guarantees all eight
 * keys, and the API seam types, which are this client's own vocabulary rather
 * than anything the wire carries.
 */

import type {
  CodeSnapshot as WireCodeSnapshot,
  CodeStageState,
} from "@sdlc/contracts-ts";
import type { CodeStageId } from "@/types/project";

export type {
  AgreementCounts,
  AgreementFinding,
  ApiContract,
  ApiContractArtefact,
  ApiEndpoint,
  ArmComparison,
  ArmCounts,
  BuildReport,
  BuildStepReport,
  CodeLocation,
  CodeRepository,
  CodeStageState,
  CodeThreadMessage,
  ContractAgreement,
  ContractConflict,
  ContractDiff,
  CountedFact,
  EndpointChange,
  EndpointSchema,
  EndpointTraces,
  EntityModel,
  GateDecision,
  GateState,
  ManifestRow,
  NextSprint,
  NextSprintStory,
  RepositoryPointer,
  SchemaField,
  ScopeStory,
  ScopeStoryTraces,
  ScorePart,
  SprintScope,
  StackCandidate,
  StackLayer,
  TechStackArtefact,
} from "@sdlc/contracts-ts";

/**
 * All eight stages, always.
 *
 * The generated type is an index signature, because JSON Schema says
 * `additionalProperties`, but the server's snapshot validator refuses to
 * return one without every key. Narrowing it here is what lets a stage panel
 * index `stages[id]` with no null guard, which is the whole reason that
 * validator exists.
 */
export type CodeStages = Record<CodeStageId, CodeStageState>;

export type CodeSnapshot = Omit<WireCodeSnapshot, "stages"> & { stages: CodeStages };

/** What the file route answers with. Not part of the snapshot: bodies are
 *  fetched one at a time, because the snapshot is polled while generating. */
export type CodeFile = { path: string; version: number; content: string };

/**
 * A running preview of the generated app.
 *
 * Not part of the snapshot: a preview is a process, not an artefact, and it
 * changes on its own cadence rather than the run's. Reading it is also what
 * tells the server somebody is still looking, so an idle one can be reclaimed
 * without guessing.
 */
export type PreviewState = {
  status: "none" | "starting" | "running" | "failed" | "stopped" | "unavailable";
  codeVersion?: number;
  url?: string | null;
  error?: string | null;
  startedAt?: string | null;
  reason?: string;
};

export type CodeDecisionInput = {
  kind: "approved" | "changes";
  by: string;
  note?: string;
};

/**
 * The seam. Fixtures answer today and the orchestrator answers when the
 * feature is flipped live; components cannot tell which, because both sides
 * return the same `CodeSnapshot`.
 */
export interface CodeApi {
  /** The api-contract at a version as an OpenAPI 3.1 document. */
  getOpenApi(projectId: string, version: number): Promise<Record<string, unknown>>;
  /** A version's generated files as a zip. */
  getArchive(projectId: string, version: number): Promise<Blob>;
  /** Push a version that was never pushed; an approved one also lands on the default branch. */
  pushVersion(projectId: string, version: number): Promise<CodeSnapshot>;
  getCode(projectId: string): Promise<CodeSnapshot>;
  getFile(projectId: string, path: string, version?: number): Promise<CodeFile>;
  /** What a code version changed since the one before it, file by file (C2-8). */
  getChanges(projectId: string, version?: number): Promise<CodeChanges>;
  /** `supersede` starts a new version over an approved one, which is refused without it. */
  generate(projectId: string, supersede?: boolean): Promise<CodeSnapshot>;
  setStoryScope(
    projectId: string,
    storyId: string,
    inScope: boolean,
    by: string,
    supersede?: boolean,
  ): Promise<CodeSnapshot>;
  /** Put the next sprint's stories into the build, as `nextSprint` shows them, and generate once. */
  planNextSprint(projectId: string, by: string, supersede?: boolean): Promise<CodeSnapshot>;
  selectStack(projectId: string, stackId: string, by: string): Promise<CodeSnapshot>;
  chooseArm(
    projectId: string,
    arm: "rule" | "llm" | "merged",
    by: string,
    supersede?: boolean,
  ): Promise<CodeSnapshot>;
  retryStage(projectId: string, stageId: CodeStageId): Promise<CodeSnapshot>;
  /** Go on with the phase's stopped run from where it stopped. */
  continueRun(projectId: string, runId: string): Promise<CodeSnapshot>;
  submitDecision(projectId: string, decision: CodeDecisionInput): Promise<CodeSnapshot>;
  getPreview(projectId: string): Promise<PreviewState>;
  startPreview(projectId: string): Promise<PreviewState>;
  stopPreview(projectId: string): Promise<void>;
}

/** One file a code version added, removed or changed, with its unified diff. */
export type FileChange = {
  path: string;
  status: "added" | "removed" | "changed";
  additions: number;
  deletions: number;
  diff: string;
  /** The diff was cut for length; the counts are of the whole change. */
  truncated: boolean;
};

/** A code version against the one before it; `againstVersion` is null for the first. */
export type CodeChanges = {
  version: number;
  againstVersion: number | null;
  files: FileChange[];
};

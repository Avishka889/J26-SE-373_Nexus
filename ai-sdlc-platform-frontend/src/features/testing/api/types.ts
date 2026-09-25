/**
 * The C3 display contract, re-exported from the generated package.
 *
 * `@sdlc/contracts-ts` is generated from the committed JSON Schemas, which are
 * generated from the Pydantic models: one author, two derived artefacts. The
 * design phase learned the alternative expensively, by hand maintaining a copy
 * of every interface behind a CI test that compared field names and could never
 * see a nullability difference.
 *
 * Two kinds of declaration are hand written and only two: `TestStages`, because
 * the generator emits an index signature where the server guarantees all seven
 * keys, and the API seam types, which are this client's own vocabulary rather
 * than anything the wire carries.
 */

import type { TestSnapshot as WireTestSnapshot, TestStageState } from "@sdlc/contracts-ts";
import type { TestStageId } from "@/types/project";

export type {
  CoverageEntry,
  CvssFactors,
  DetectorRun,
  EvidenceSpan,
  FindingDecision,
  FixShipsWith,
  GateDecision,
  GateState,
  HealAttempt,
  HealReport,
  MutationResult,
  PatchHunk,
  QualityFinding,
  RefusedFinding,
  RemediationProposal,
  RemediationProposals,
  Reverification,
  RiskAssessment,
  SecurityFinding,
  TestCase,
  TestReport,
  TestStageState,
  TestSuite,
  TestThreadMessage,
  ToolStep,
  ValidationReport,
  VerificationSnapshot,
} from "@sdlc/contracts-ts";

/**
 * All seven stages, always.
 *
 * The generated type is an index signature, because JSON Schema says
 * `additionalProperties`, but the server's snapshot validator refuses to return
 * one without every key. Narrowing it here is what lets a stage panel index
 * `stages[id]` with no null guard, which is the whole reason that validator
 * exists.
 */
export type TestStages = Record<TestStageId, TestStageState>;

export type TestSnapshot = Omit<WireTestSnapshot, "stages"> & { stages: TestStages };

export type TestDecisionInput = {
  kind: "approved" | "changes";
  by: string;
  note?: string;
};

/** A decision about one finding, taken inside the stage rather than at the gate. */
export type FindingDecisionInput = {
  decision: "accepted" | "dismissed";
  by: string;
  note?: string;
};

/** A decision about one proposed fix. */
export type ProposalDecisionInput = FindingDecisionInput;

/** A repository this phase can be pointed at, as the component offers it. */
export type TestTarget = {
  id: string;
  label: string;
  stack: string;
  detail: string;
};

/** Who applied or re-verified a fix. Both are recorded against a person. */
export type ActorInput = {
  by: string;
  note?: string;
};

/** A reader overriding what the healing loop did with one test. */
export type HealDecisionInput = {
  decision: "kept" | "reverted";
  by: string;
  note?: string;
};

/**
 * A person's decision about one failing generated test no repair will fix:
 * quarantine it, restore it, or send one that never passed back to be written
 * again. The note is required for the first and the last.
 */
export type FailingTestDecisionInput = {
  decision: "quarantined" | "restored" | "rewrite";
  by: string;
  note?: string;
};

/**
 * The seam. Fixtures answer until the feature is flipped live and the
 * orchestrator answers after; components cannot tell which, because both sides
 * return the same `TestSnapshot`.
 *
 * Every mutation answers with the whole snapshot, which is what lets a caller
 * write one response into its cache rather than reconcile a partial update
 * against what it already had.
 */
/** One test file, as the code version the tests ran against holds it. */
export type TestFile = { path: string; version: number; content: string };

export interface TestingApi {
  getTesting(projectId: string): Promise<TestSnapshot>;
  /**
   * One test file, by path, at the code version the run tested. Its own call,
   * as Code Generation's files are, so the snapshot polled during a run stays
   * small. The tests live beside the code they test, in the same file store.
   */
  getTestFile(projectId: string, path: string, version: number): Promise<TestFile>;
  /**
   * What this phase can be pointed at.
   *
   * Asked of the server rather than listed here: which samples exist is a fact
   * about the component's fixtures, and a copy on this side would offer a
   * target no run can resolve the first time one is removed.
   */
  listTargets(projectId: string): Promise<TestTarget[]>;
  /** Point this project's runs at one of them. */
  chooseTarget(projectId: string, target: string, by: string): Promise<TestSnapshot>;
  run(projectId: string): Promise<TestSnapshot>;
  retryStage(projectId: string, stageId: TestStageId): Promise<TestSnapshot>;
  /** Go on with the phase's stopped run from where it stopped. */
  continueRun(projectId: string, runId: string): Promise<TestSnapshot>;
  decideFinding(
    projectId: string,
    findingId: string,
    decision: FindingDecisionInput,
  ): Promise<TestSnapshot>;
  decideProposal(
    projectId: string,
    proposalId: string,
    decision: ProposalDecisionInput,
  ): Promise<TestSnapshot>;
  decideHeal(
    projectId: string,
    testId: string,
    decision: HealDecisionInput,
  ): Promise<TestSnapshot>;
  decideTest(
    projectId: string,
    testId: string,
    decision: FailingTestDecisionInput,
  ): Promise<TestSnapshot>;
  /**
   * Put an accepted fix into the code, as a new code version.
   *
   * Separate from accepting it, because the two are different acts: one is a
   * decision and the other writes source. The server refuses to apply a fix
   * nobody accepted, and refuses a patch that no longer fits the file.
   */
  applyProposal(projectId: string, proposalId: string, actor: ActorInput): Promise<TestSnapshot>;
  /**
   * Ask whether an applied fix worked, by subtracting two testing runs.
   *
   * Needs a run against the patched code version to exist. The server says so
   * rather than inventing an answer when none has happened yet.
   */
  reverifyProposal(projectId: string, proposalId: string, actor: ActorInput): Promise<TestSnapshot>;
  submitDecision(projectId: string, decision: TestDecisionInput): Promise<TestSnapshot>;
}

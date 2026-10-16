import type { FileEntry } from "@/shared/code-viewer/buildFileTree";

export type SuiteModule = {
  id: string;
  name: string;
  side: "backend" | "frontend";
  runner: "JUnit 5" | "Vitest";
  passed: number;
  failed: number;
  skipped: number;
  duration: string;
  requirements: string[];
  failureIds: string[];
  /** Tests this version first ran, and tests it carried from an earlier one. */
  fresh?: number;
  carried?: number;
};

// The Console moved to `shared/ui/console` when the code phase needed it for
// build logs, and its line type went with it. Imported and re-exported, so
// nothing in Testing had to change its imports and the types below can still
// name it.
import type { ConsoleLine } from "@/shared/ui/console";

export type { ConsoleLine };

/**
 * `unclassified`: failing, and nothing has said whether the test or the code is wrong,
 * because there was no earlier tested version to compare with or the classifier
 * could not decide. It was filed under regressions, which it may not be.
 */
export type Triage = "brittle" | "regression" | "healed" | "unclassified";

export type GuardCheck = { pass: boolean; detail: string };

export type Repair = {
  proposedAt: string;
  /** The test file the repair changes; live repairs carry it, for the diff's header. */
  path?: string;
  language: "java" | "tsx";
  /** Empty when only the patch is known: then `proposed` is a unified diff. */
  original: string;
  proposed: string;
  guard: { unchanged: GuardCheck; planted: GuardCheck };
  verdictLine: string;
  why: string;
};

export type FailureItem = {
  id: string;
  test: string;
  moduleId: string;
  runner: "JUnit 5" | "Vitest";
  triage: Triage;
  /** brittle: awaiting your approval, or blocked by the guard and escalated */
  state: "awaiting-approval" | "blocked" | "escalated" | "healed" | "quarantined";
  reason: string;
  age: string;
  at: string;
  build: number;
  requirement: { id: string; title: string };
  file: string;
  line: number;
  owner?: string;
  repair?: Repair;
  note?: string;
};

export type TestFileMeta = {
  requirement: string;
  requirementTitle: string;
  failureId?: string;
  healedId?: string;
};

export type Quality = {
  line: { percent: number; covered: number; total: number };
  branch: { percent: number; covered: number; total: number };
  mutation: { total: number; killed: number; survived: number; score: number };
  tool: string;
  byModule: {
    name: string;
    /** Where the file is in the repository. Absent in the demo, which names modules. */
    path?: string;
    line: number;
    branch: number;
    /** How many branches the file has; zero means "no branches", not "0%". Absent in the demo. */
    branches?: number;
    covered: number;
    total: number;
  }[];
  survivors: { location: string; change: string; note: string }[];
  trend: { build: number; line: number; branch: number }[];
  trendNote: string;
  /**
   * False when mutation testing did not run, with the reason beside it: the
   * page showed "0%" as a measurement it never made. Absent in the demo, which
   * always ran it.
   */
  mutationRan?: boolean;
  mutationSkippedReason?: string;
  /**
   * The apps in the mutation scope that gave no score, each with why, so a
   * score over part of the scope says which part. Absent in the demo.
   */
  mutationNotMeasured?: { app: string; reason: string }[];
  /** What the quality checks found about the tests, apart from the mutants. */
  findings?: { location: string; change: string; note: string }[];
};

export type Severity = "critical" | "high" | "medium" | "low" | "none";
// `fix-applied`: the patch is a new code version, and nothing has measured it
// yet. Not "re-verifying", which is a run in progress: re-verification waits
// on the reader running the tests again, and a spinner would claim otherwise.
export type FindingStatus = "open" | "fix-proposed" | "fix-applied" | "re-verifying" | "verified" | "dismissed";
export type Detector = "local" | "reviewer";

export type Finding = {
  id: string;
  cwe: string;
  name: string;
  severity: Severity;
  cvss: number;
  file: string;
  line: number;
  status: FindingStatus;
  foundBy: Detector[];
  explanation: string;
  fix?: { before: string; after: string; language: "java" | "tsx"; summary: string };
  /** The fix the remediation stage proposed for this finding, when it proposed one. */
  proposal?: FindingProposal;
  openReason?: string;
  /**
   * The reason a person accepted the risk of this finding, when they did: it is
   * still open, and the release gate lets it ship (G8, review item C3-8).
   */
  riskAccepted?: string;
};

export type FindingProposal = {
  id: string;
  summary: string;
  /** One unified diff per file, exactly as the stage wrote it. */
  hunks: { path: string; diff: string }[];
  state: "proposed" | "dismissed" | "accepted" | "applied" | "verified" | "rolled-back";
  /** The stage's own sentence on how risky the patch is. */
  risk: string;
  appliedCodeVersion: number | null;
};

export type ProofState = "pass" | "fail" | "running" | "pending" | "errored";

export type AppliedFix = {
  findingId: string;
  appliedBy: string;
  appliedAt: string;
  scan: { state: ProofState; detail: string; at?: string };
  suite: { state: ProofState; detail: string; at?: string };
  verdict: string;
  /** Why to re-verify, when it is asked again rather than for the first time. */
  pendingNote?: string;
};

export type AuditActorKind = "human" | "agent" | "guard";

export type AuditEntry = {
  id: string;
  at: string;
  actor: string;
  actorKind: AuditActorKind;
  action: string;
  target: string;
  detail: string;
};

export type TestingRun = {
  sprint: string;
  build: number;
  branch: string;
  startedAt: string;
  finishedAt: string;
  duration: string;
  frontendRunner: string;
  backendRunner: string;
  lastVerified: {
    sprint: string;
    build: number;
    at: string;
    note: string;
  };
};

export type GreenRun = {
  build: number;
  finishedAt: string;
  duration: string;
  quality: {
    line: { percent: number; covered: number; total: number };
    branch: { percent: number; covered: number; total: number };
    mutation: { total: number; killed: number; survived: number; score: number };
  };
  lateFixes: Record<
    string,
    { language: "java" | "tsx"; summary: string; before: string; after: string }
  >;
  transcript: ConsoleLine[];
};

export type DecisionChainStep = {
  id: string;
  label: string;
  detail: string;
};

export type DetectorComparison = {
  caption: string;
  rows: {
    detector: string;
    precision: number;
    recall: number;
    f1: number;
    cost: string;
    latency: string;
    offline: boolean;
  }[];
};

export type { FileEntry };

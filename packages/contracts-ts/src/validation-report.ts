/**
 * Generated from contracts/*.schema.json. Do not edit by hand.
 *
 * Regenerate with: npm run gen:contracts
 * The schemas themselves are generated from the Pydantic models in
 * packages/contracts-py, which are the single author of every artefact shape.
 */

export type Approvedat = string | null;
export type Approvedby = string | null;
export type Arm = "scanner" | "llm" | "trained";
export type Completiontokens = number;
export type Costusd = number | null;
export type Durationseconds = number;
export type Filesscanned = number;
export type Modelid = string;
export type Offline = boolean;
export type Prompttokens = number;
export type Startedat = string;
export type Detectorruns = DetectorRun[];
export type Basescore = number;
export type Confidence = number;
export type Confidencesource = "arm-agreement" | "scanner-rule" | "calibration";
export type Cwe = string;
export type Endline = number;
export type Path = string;
export type Snippet = string;
export type Startline = number;
export type Explanation = string;
export type Attackcomplexity = "L" | "H";
export type Attackvector = "N" | "A" | "L" | "P";
export type Availability = "N" | "L" | "H";
export type Confidentiality = "N" | "L" | "H";
export type Integrity = "N" | "L" | "H";
export type Privilegesrequired = "N" | "L" | "H";
export type Scope = "U" | "C";
export type Userinteraction = "N" | "R";
export type Vector = string;
export type Id = string;
export type Origin = "scanner" | "llm" | "trained" | "merged";
/**
 * @minItems 1
 */
export type Raisedby = ["scanner" | "llm" | "trained", ...("scanner" | "llm" | "trained")[]];
export type Remediation = string;
export type Runid = string;
export type Severity = "none" | "low" | "medium" | "high" | "critical";
export type Severityreasoning = string;
export type Status = "open" | "dismissed" | "fix-proposed" | "re-verifying" | "verified";
export type Title = string;
export type Findings = SecurityFinding[];
export type Generatedat = string;
export type Opencriticalorhigh = number;
export type Openfindings = number;
export type Refusedcount = number;
export type Claimedpath = string;
export type Claimedstartline = number | null;
export type Cwe1 = string;
export type Detail = string;
export type Origin1 = "scanner" | "llm" | "trained";
export type Reason =
  "file-not-found" | "span-out-of-range" | "snippet-does-not-match" | "malformed-cwe" | "no-evidence";
export type Refusedevidence = RefusedFinding[];
export type Reportversion = string;
export type Target = string;
export type Failed = number;
export type Linecoverage = number;
export type Mutationscore = number | null;
export type Passed = number;
export type Run = number;
export type Skipped = number;
export type Detail1 = string;
export type Ran = boolean;
export type Tool = string;
export type Version = string;
export type Tools = ToolOutcome[];
export type Version1 = number;

export interface ValidationReport {
  approvedAt: Approvedat;
  approvedBy: Approvedby;
  detectorRuns: Detectorruns;
  findings: Findings;
  generatedAt: Generatedat;
  openCriticalOrHigh: Opencriticalorhigh;
  openFindings: Openfindings;
  refusedCount: Refusedcount;
  refusedEvidence: Refusedevidence;
  reportVersion: Reportversion;
  target: Target;
  tests: TestSummary;
  tools: Tools;
  version: Version1;
}
/**
 * One arm's pass over one target: the operational half of the study.
 *
 * Cost, latency and offline operation are reported beside accuracy because
 * the trained arm's argument is largely made of them, and a comparison that
 * reports only F1 cannot see it.
 */
export interface DetectorRun {
  arm: Arm;
  completionTokens: Completiontokens;
  costUsd: Costusd;
  durationSeconds: Durationseconds;
  filesScanned: Filesscanned;
  modelId: Modelid;
  offline: Offline;
  promptTokens: Prompttokens;
  startedAt: Startedat;
}
export interface SecurityFinding {
  baseScore: Basescore;
  confidence: Confidence;
  confidenceSource: Confidencesource;
  cwe: Cwe;
  evidence: EvidenceSpan;
  explanation: Explanation;
  factors: CvssFactors;
  id: Id;
  origin: Origin;
  raisedBy: Raisedby;
  remediation: Remediation;
  runId: Runid;
  severity: Severity;
  severityReasoning: Severityreasoning;
  status: Status;
  title: Title;
}
/**
 * Where in the repository the finding is, precisely enough to check.
 *
 * A span rather than a line, because a taint finding is a flow and a reader
 * asked to confirm one line of it is being asked to trust the rest.
 */
export interface EvidenceSpan {
  endLine: Endline;
  path: Path;
  snippet: Snippet;
  startLine: Startline;
}
/**
 * The CVSS v3.1 base metrics. Inputs, so the score is checkable.
 *
 * Kept as the metric letters rather than numbers because that is what the
 * vector string carries and what a reader can compare against a published
 * CVE. The weights live in the scoring code, once.
 */
export interface CvssFactors {
  attackComplexity: Attackcomplexity;
  attackVector: Attackvector;
  availability: Availability;
  confidentiality: Confidentiality;
  integrity: Integrity;
  privilegesRequired: Privilegesrequired;
  scope: Scope;
  userInteraction: Userinteraction;
  vector: Vector;
}
/**
 * A finding that was thrown away, and why. Counted, never silent.
 *
 * The refusal rate is a result about the arm that produced it: an arm whose
 * evidence does not resolve is an arm inventing locations, and dropping those
 * quietly would flatter it in exactly the comparison this component exists to
 * run.
 */
export interface RefusedFinding {
  claimedPath: Claimedpath;
  claimedStartLine: Claimedstartline;
  cwe: Cwe1;
  detail: Detail;
  origin: Origin1;
  reason: Reason;
}
/**
 * The test side in one block, so C4 reads one artefact rather than two.
 */
export interface TestSummary {
  failed: Failed;
  lineCoverage: Linecoverage;
  mutationScore: Mutationscore;
  passed: Passed;
  run: Run;
  skipped: Skipped;
}
/**
 * One scanning tool in a pass: whether it ran, and if not, why.
 *
 * A tool that failed and a tool that found nothing look the same in a list of
 * zero findings, and only one of them is a result. The failure reached only
 * the stage's notes, so the Security step could not say that npm audit had
 * never run on a generated app (review item C3-5).
 */
export interface ToolOutcome {
  detail: Detail1;
  ran: Ran;
  tool: Tool;
  version: Version;
}

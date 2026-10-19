/**
 * Generated from contracts/*.schema.json. Do not edit by hand.
 *
 * Regenerate with: npm run gen:contracts
 * The schemas themselves are generated from the Pydantic models in
 * packages/contracts-py, which are the single author of every artefact shape.
 */

export type Affectedcomponents = string[];
export type Affectedfiles = string[];
export type Advisory = string;
export type Decidedby = ("semver" | "changelog" | "usage")[];
export type Final = "low" | "medium" | "high";
export type Ruleid = "safety-first-max/1";
export type Change =
  | "major"
  | "minor"
  | "patch"
  | "prerelease"
  | "build-only"
  | "beyond-patch"
  | "qualifier"
  | "downgrade"
  | "non-semver"
  | "unparseable";
export type Disagreement = boolean;
export type Ecosystem = "npm" | "maven";
export type Id = string;
export type Kind = "version" | "claim" | "reference" | "api-diff" | "component";
export type Summary = string;
export type Evidence = EvidenceRef[];
/**
 * Every vote that was cast cites at least one piece of evidence.
 */
export type Evidencecomplete = boolean;
export type Explanation = string;
export type Completiontokens = number;
export type Durationseconds = number;
export type Error = string;
export type Modelid = string;
export type Outcome = "answered" | "malformed" | "cut-off" | "rate-limited" | "provider-error";
export type Promptid = string;
export type Promptsha256 = string;
export type Prompttokens = number;
export type Requests = number;
export type Maxtokens = number | null;
export type Temperature = number | null;
export type Thinking = string | null;
export type Statedlevel = ("low" | "medium" | "high") | null;
export type Explanationdashesreplaced = number;
export type Explanationrefusal = string;
export type Explanationsource = "model" | "rule" | "none";
export type Explanationunavailable = string;
export type Fromversion = string;
export type Key = string;
export type Arbitrationseconds = number;
export type Assessmentseconds = number;
export type Changelogseconds = number;
export type Retrievalseconds = number;
export type Usageseconds = number;
export type Package = string;
export type Deploy = "automatic" | "approval" | "approval-with-rollback";
export type Manualreviewrequired = boolean;
export type Rollbackrequired = boolean;
export type Ruleid1 = "risk-strategy/1";
export type Toversion = string;
export type Updateid = string;
export type Abstainedreason = string;
export type Evidenceids = string[];
export type Level = ("low" | "medium" | "high") | null;
export type Rationale = string;
export type Ruleid2 = string;
export type Signal = "semver" | "changelog" | "usage";
export type Votes = SignalVote[];
export type Assessments = UpdateAssessment[];
export type Disagreements = number;
export type Evidenceincomplete = number;
export type Explanationmodelid = string;
export type Explanationpromptid = string;
export type Explanationpromptsha256 = string;
/**
 * Model answers the check refused, each replaced by a rule written summary.
 */
export type Explanationsrefused = number;
export type Generatedat = string;
export type Latencybudgetseconds = number;
export type Overbudget = number;
export type Arbitration1 = "safety-first-max/1";
export type Changelog = "changelog-rule/1";
export type Semver = "semver-rule/1";
export type Strategy1 = "risk-strategy/1";
export type Usage = "usage-rule/1";
export type Version = number;

/**
 * The `risk-report` artefact: every update at one deploy version, assessed.
 */
export interface RiskReport {
  assessments: Assessments;
  byLevel: Bylevel;
  disagreements: Disagreements;
  evidenceIncomplete: Evidenceincomplete;
  explanationModelId: Explanationmodelid;
  explanationPromptId: Explanationpromptid;
  explanationPromptSha256: Explanationpromptsha256;
  explanationsRefused: Explanationsrefused;
  generatedAt: Generatedat;
  latencyBudgetSeconds: Latencybudgetseconds;
  overBudget: Overbudget;
  rules: RuleSet;
  version: Version;
}
/**
 * One update, assessed.
 */
export interface UpdateAssessment {
  affectedComponents: Affectedcomponents;
  affectedFiles: Affectedfiles;
  arbitration: Arbitration;
  change: Change;
  disagreement: Disagreement;
  ecosystem: Ecosystem;
  evidence: Evidence;
  evidenceComplete: Evidencecomplete;
  explanation: Explanation;
  explanationCall: ModelCall | null;
  explanationDashesReplaced: Explanationdashesreplaced;
  explanationRefusal: Explanationrefusal;
  explanationSource: Explanationsource;
  explanationUnavailable: Explanationunavailable;
  fromVersion: Fromversion;
  key: Key;
  latency: Latency;
  package: Package;
  strategy: Strategy;
  toVersion: Toversion;
  updateId: Updateid;
  votes: Votes;
}
/**
 * How the votes became one level (FR6, FR7).
 */
export interface Arbitration {
  advisory: Advisory;
  decidedBy: Decidedby;
  final: Final;
  ruleId: Ruleid;
}
/**
 * One piece of evidence a vote rests on, summarised for a reader.
 */
export interface EvidenceRef {
  id: Id;
  kind: Kind;
  summary: Summary;
}
/**
 * One call to the model, whatever came of it (NFR13).
 */
export interface ModelCall {
  completionTokens: Completiontokens;
  durationSeconds: Durationseconds;
  error: Error;
  modelId: Modelid;
  outcome: Outcome;
  promptId: Promptid;
  promptSha256: Promptsha256;
  promptTokens: Prompttokens;
  requests: Requests;
  settings: ModelCallSettings;
  statedLevel: Statedlevel;
}
/**
 * The settings the call was made with, recorded because they change answers.
 */
export interface ModelCallSettings {
  maxTokens: Maxtokens;
  temperature: Temperature;
  thinking: Thinking;
}
/**
 * Seconds spent per step for one update (NFR1).
 *
 * The assessment is the changelog step, the usage step and the arbitration.
 * Retrieval is reported beside it rather than inside it, because NFR1 bounds
 * the assessment and a slow registry is not the engine being slow.
 */
export interface Latency {
  arbitrationSeconds: Arbitrationseconds;
  assessmentSeconds: Assessmentseconds;
  changelogSeconds: Changelogseconds;
  retrievalSeconds: Retrievalseconds;
  usageSeconds: Usageseconds;
}
/**
 * How an update at this level may ship (FR17, FR18, FR19).
 */
export interface Strategy {
  deploy: Deploy;
  manualReviewRequired: Manualreviewrequired;
  rollbackRequired: Rollbackrequired;
  ruleId: Ruleid1;
}
/**
 * One signal's answer for one update, or its reason for having none.
 */
export interface SignalVote {
  abstainedReason: Abstainedreason;
  evidenceIds: Evidenceids;
  level: Level;
  rationale: Rationale;
  ruleId: Ruleid2;
  signal: Signal;
}
export interface Bylevel {
  [k: string]: number;
}
/**
 * The rule ids this report was produced under, so a table can name them.
 */
export interface RuleSet {
  arbitration: Arbitration1;
  changelog: Changelog;
  semver: Semver;
  strategy: Strategy1;
  usage: Usage;
}

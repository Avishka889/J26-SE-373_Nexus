/**
 * Generated from contracts/*.schema.json. Do not edit by hand.
 *
 * Regenerate with: npm run gen:contracts
 * The schemas themselves are generated from the Pydantic models in
 * packages/contracts-py, which are the single author of every artefact shape.
 */

export type Awaitingdecision = number;
export type Generatedat = string;
export type Affectedendpoints = string[];
export type Affectedtests = string[];
export type Appliedcodeversion = number | null;
export type Awaitingdecision1 = boolean;
export type Cwe = string;
export type Decidedat = string | null;
export type Decidedby = string;
export type Decisionnote = string;
export type Findingid = string;
export type Generatedat1 = string;
export type Id = string;
/**
 * @minItems 1
 */
export type Patch = [PatchHunk, ...PatchHunk[]];
export type Diff = string;
export type Path = string;
export type Mutationscore = number | null;
export type Openfindings = number;
export type Testsfailed = number;
export type Testspassed = number;
export type Afterrunid = string;
export type Beforerunid = string;
/**
 * Whether the finding the fix was for is gone. A comparison that never
 * looked for it proves nothing about it, so that is not closed.
 */
export type Findingclosed = boolean;
export type Findingid1 = string;
export type Findingsclosed = number;
export type Stillraisedas = string[];
export type Testsbroken = number;
/**
 * The fix closed its finding and made nothing worse. Totals alone
 * called a fix verified with its own finding still raised (C3-7).
 */
export type Verified = boolean;
export type Worsened = boolean;
/**
 * @minItems 1
 */
export type Facts = [CountedFact, ...CountedFact[]];
export type Label = string;
export type Value = number;
export type Level = "low" | "medium" | "high";
export type Statement = string;
export type State = "proposed" | "dismissed" | "accepted" | "applied" | "verified" | "rolled-back";
export type Summary = string;
export type Proposals = RemediationProposal[];
export type Target = string;
export type Version = number;

/**
 * Every proposal one scan produced, as one stored artefact.
 *
 * The artefact kind is `remediation-proposal` because that is what it is
 * about; the body is a set because a scan answers several findings at once
 * and storing one artefact per proposal would put the version axis in a place
 * it does not belong.
 */
export interface RemediationProposals {
  awaitingDecision: Awaitingdecision;
  generatedAt: Generatedat;
  proposals: Proposals;
  target: Target;
  version: Version;
}
export interface RemediationProposal {
  affectedEndpoints: Affectedendpoints;
  affectedTests: Affectedtests;
  appliedCodeVersion: Appliedcodeversion;
  awaitingDecision: Awaitingdecision1;
  cwe: Cwe;
  decidedAt: Decidedat;
  decidedBy: Decidedby;
  decisionNote: Decisionnote;
  findingId: Findingid;
  generatedAt: Generatedat1;
  id: Id;
  patch: Patch;
  reverification: Reverification | null;
  risk: RiskAssessment;
  state: State;
  summary: Summary;
}
/**
 * One file's worth of the proposed change.
 *
 * Production code, unlike a heal's diff, because this is the other loop: a
 * heal may only touch test code and a remediation may only touch the code the
 * finding was about. The two are separate artefacts partly so that rule can
 * be enforced separately.
 */
export interface PatchHunk {
  diff: Diff;
  path: Path;
}
/**
 * Before and after, and what the difference says.
 *
 * `worsened` is computed rather than asserted so that "re-verification
 * passed" cannot be recorded over numbers that say otherwise. A fix that
 * closes its finding while breaking a test has not passed, and the rollback
 * offer is meant to follow from the arithmetic.
 */
export interface Reverification {
  after: VerificationSnapshot;
  afterRunId: Afterrunid;
  before: VerificationSnapshot;
  beforeRunId: Beforerunid;
  findingClosed: Findingclosed;
  findingId: Findingid1;
  findingsClosed: Findingsclosed;
  stillRaisedAs: Stillraisedas;
  testsBroken: Testsbroken;
  verified: Verified;
  worsened: Worsened;
}
/**
 * The measurable state of the target at one moment.
 */
export interface VerificationSnapshot {
  mutationScore: Mutationscore;
  openFindings: Openfindings;
  testsFailed: Testsfailed;
  testsPassed: Testspassed;
}
/**
 * Why this change is as safe or as dangerous as it is claimed to be.
 */
export interface RiskAssessment {
  facts: Facts;
  level: Level;
  statement: Statement;
}
/**
 * One number the scoring rests on, named so a reader can check it.
 */
export interface CountedFact {
  label: Label;
  value: Value;
}

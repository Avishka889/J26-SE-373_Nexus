/**
 * Generated from contracts/*.schema.json. Do not edit by hand.
 *
 * Regenerate with: npm run gen:contracts
 * The schemas themselves are generated from the Pydantic models in
 * packages/contracts-py, which are the single author of every artefact shape.
 */

/**
 * All three checks, and a repair to apply them to.
 *
 * Computed rather than stored: acceptance is the conjunction of the
 * guard's conditions, and a stored flag is a place for it to be set
 * without them.
 */
export type Accepted = boolean;
export type Attempts1 = number;
export type Detail = string;
export type Name = "test-code-only" | "passes-unchanged-code" | "kills-a-mutant";
export type Passed = boolean;
export type Checks = GuardCheck[];
export type Classification = "brittle" | "regression" | "undecided";
export type Classifiedby = "trace-changed" | "trace-unchanged" | "model-referee" | "unclassified";
export type Diff = string;
export type Path = string;
export type Changedartefacts = string[];
export type Citeddiffspan = string;
export type Refereereasoning = string;
export type Tracedto = string[];
export type Failuremessage = string;
export type Killedmutantids = string[];
export type Passedonunchangedrunid = string;
export type Refusalreason =
  | (
      | "touched-production-code"
      | "assertion-weakened"
      | "test-deleted"
      | "still-failing"
      | "kills-no-mutant"
      | "no-repair-produced"
      | "malformed-output"
      | "no-code-to-check"
    )
  | null;
export type Rejecteddrafts = string[];
export type Suitepath = string;
export type Testid = string;
export type Testname = string;
export type Attempts = HealAttempt[];
export type Flaggedregressions = number;
export type Fromcodeversion = number;
export type Generatedat = string;
export type Healed = number;
/**
 * The number a loop without the guard would have reported.
 *
 * Every brittle test the model produced a repair for, whether or not the
 * repair kept the test's power. Reported beside the strict rate because
 * the gap between them is the guard's effect, and the gap is the result.
 */
export type Naiveconvergence = number;
export type Refused = number;
/**
 * The number this loop reports: repairs that cleared the guard.
 */
export type Strictconvergence = number;
export type Target = string;
export type Tocodeversion = number;
export type Version = number;

/**
 * One pass of the loop over one version's failures.
 *
 * Outlives the test report that produced it. A test report is replaced by the
 * next run; a refused repair is evidence about how the model behaves, and the
 * study reads it long after the suite has moved on.
 */
export interface HealReport {
  attempts: Attempts;
  flaggedRegressions: Flaggedregressions;
  fromCodeVersion: Fromcodeversion;
  generatedAt: Generatedat;
  healed: Healed;
  naiveConvergence: Naiveconvergence;
  refused: Refused;
  strictConvergence: Strictconvergence;
  target: Target;
  toCodeVersion: Tocodeversion;
  version: Version;
}
/**
 * One failing test, and what happened to it.
 *
 * Accepted and refused attempts share this shape deliberately: they are the
 * same event with different outcomes, and separating them into two lists is
 * how a refusal rate stops being reported.
 */
export interface HealAttempt {
  accepted: Accepted;
  attempts: Attempts1;
  checks: Checks;
  classification: Classification;
  classifiedBy: Classifiedby;
  diff: DiffSpan | null;
  evidence: ClassificationEvidence;
  failureMessage: Failuremessage;
  killedMutantIds: Killedmutantids;
  passedOnUnchangedRunId: Passedonunchangedrunid;
  refusalReason: Refusalreason;
  rejectedDrafts: Rejecteddrafts;
  suitePath: Suitepath;
  testId: Testid;
  testName: Testname;
}
/**
 * One of the three conditions, with what was observed.
 *
 * `detail` is not optional prose. A guard that says False without saying what
 * it saw cannot be argued with, and the point of the guard is that a person
 * can check it.
 */
export interface GuardCheck {
  detail: Detail;
  name: Name;
  passed: Passed;
}
/**
 * The change, as a unified diff over test files only.
 *
 * Kept verbatim rather than summarised. A refusal whose diff is paraphrased
 * cannot be audited, and the refused diffs are the evidence this component is
 * judged on.
 */
export interface DiffSpan {
  diff: Diff;
  path: Path;
}
/**
 * Why this failure was called brittle or a regression.
 *
 * `changed_artefacts` is what the test traces to that moved between the two
 * versions, and it is the whole argument when the rules decide alone. The
 * referee's citation is required when the model decided, because a verdict
 * that cannot point at a diff is a guess with a confident tone.
 */
export interface ClassificationEvidence {
  changedArtefacts: Changedartefacts;
  citedDiffSpan: Citeddiffspan;
  refereeReasoning: Refereereasoning;
  tracedTo: Tracedto;
}

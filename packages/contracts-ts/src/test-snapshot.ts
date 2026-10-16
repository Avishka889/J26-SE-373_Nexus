/**
 * Generated from contracts/*.schema.json. Do not edit by hand.
 *
 * Regenerate with: npm run gen:contracts
 * The schemas themselves are generated from the Pydantic models in
 * packages/contracts-py, which are the single author of every artefact shape.
 */

export type Action = string;
export type Actor = string;
export type At = string;
export type Detail = string;
export type Target = string;
export type Audit = TestAuditEntry[];
export type Awaitingdecision = number;
/**
 * Whether the tests describe a version that is no longer current.
 *
 * Derived rather than stored. A green report about a code version two
 * behind is the most misleading thing this phase can show, and a reader
 * should be told by the payload rather than by noticing two numbers.
 */
export type Codemovedon = boolean;
export type Codeversion = number;
export type At1 = string;
export type By = string;
export type Decision = "accepted" | "dismissed";
export type Findingid = string;
export type Note = string;
export type Findingdecisions = FindingDecision[];
export type Codeversion1 = number;
export type Releasablecodeversion = number;
export type Releasablesprint = number;
export type Sprint = number;
export type At2 = string;
export type By1 = string;
export type Kind = "approved" | "changes";
export type Note1 = string | null;
export type Version = number;
export type History = GateDecision[];
/**
 * All three checks, and a repair to apply them to.
 *
 * Computed rather than stored: acceptance is the conjunction of the
 * guard's conditions, and a stored flag is a place for it to be set
 * without them.
 */
export type Accepted = boolean;
export type Attempts1 = number;
export type Detail1 = string;
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
export type Target1 = string;
export type Tocodeversion = number;
export type Version1 = number;
export type At3 = string;
export type By2 = string;
export type Decision1 = "kept" | "reverted" | "quarantined" | "restored" | "rewrite";
export type Note2 = string;
export type Testid1 = string;
export type Healdecisions = HealDecision[];
export type Openfindings = number;
export type Projectid = string;
/**
 * Repairs the guard would not accept. The headline count of the
 * component's contribution, so it is on the payload rather than behind a
 * route the dashboard might not call.
 */
export type Refusedrepairs = number;
export type Awaitingdecision1 = number;
export type Generatedat1 = string;
export type Affectedendpoints = string[];
export type Affectedtests = string[];
export type Appliedcodeversion = number | null;
export type Awaitingdecision2 = boolean;
export type Cwe = string;
export type Decidedat = string | null;
export type Decidedby = string;
export type Decisionnote = string;
export type Findingid1 = string;
export type Generatedat2 = string;
export type Id = string;
/**
 * @minItems 1
 */
export type Patch = [PatchHunk, ...PatchHunk[]];
export type Diff1 = string;
export type Path1 = string;
export type Mutationscore = number | null;
export type Openfindings1 = number;
export type Testsfailed = number;
export type Testspassed = number;
export type Afterrunid = string;
export type Beforerunid = string;
/**
 * Whether the finding the fix was for is gone. A comparison that never
 * looked for it proves nothing about it, so that is not closed.
 */
export type Findingclosed = boolean;
export type Findingid2 = string;
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
export type Target2 = string;
export type Version2 = number;
export type Error = string | null;
export type Finishedat = string | null;
export type Id1 = string;
export type Model = string | null;
export type Startedat = string;
export type State1 = "queued" | "running" | "awaiting_gate" | "done" | "failed" | "superseded";
export type Stoppedat = string | null;
export type Thinking = string | null;
export type Version3 = number;
export type Error1 = string | null;
export type Generatedat3 = string | null;
export type Generatedfromversion = number;
export type Id2 =
  "test-generation" | "test-run" | "test-quality" | "self-healing" | "security-scan" | "remediation" | "test-review";
/**
 * @minItems 1
 */
export type Answeredby = [string, ...string[]];
export type Reasoningtokens = number;
export type Requests = number;
export type Thinking1 = string[];
export type Tokensin = number;
export type Tokensout = number;
export type Status = "pending" | "generating" | "complete" | "failed" | "skipped";
export type Summary1 = string | null;
export type Target3 = string;
export type Testversion = number;
export type Testedcodeversion = number;
export type Branchcoverage = number;
export type Branchpercent = number;
export type Branchescovered = number;
export type Branchestotal = number;
export type Linepercent = number;
export type Linescovered = number;
export type Linestotal = number;
export type Module = string;
export type Coverage = CoverageEntry[];
export type Failed = number;
export type Detail2 = string;
export type Endpointid = string;
export type Kind1 = string;
export type Gaps = TestGap[];
export type Generatedat4 = string;
export type Isolation = string;
/**
 * Weighted by lines, not the mean of the per module percentages.
 *
 * Averaging percentages weights a ten line module the same as a thousand
 * line one, which is how a coverage number ends up describing nothing.
 */
export type Linecoverage = number;
export type Durationseconds = number;
export type Inconclusive = string[];
export type Killed = string[];
export type App = string;
export type Reason = string;
export type Notmeasured = UnmeasuredApp[];
/**
 * @minItems 1
 */
export type Scope = [string, ...string[]];
/**
 * Killed over killed plus survived, as every mutation tool defines it.
 *
 * Inconclusive mutants are excluded from the denominator rather than
 * counted as survivors, because a mutant that could not be evaluated is
 * not evidence that a test missed it.
 */
export type Score = number;
export type Survived = string[];
export type Tool = string;
export type Total = number;
export type Mutationskippedreason = string;
export type Notrun = number;
export type Passed1 = number;
export type Detail3 = string;
export type Observed = boolean;
export type Path2 = string;
export type Rule =
  | "no-assertion"
  | "vacuous-assertion"
  | "focused"
  | "sleep"
  | "unseeded-randomness"
  | "wall-clock"
  | "network"
  | "order-dependent"
  | "kills-no-mutant";
export type Test = string;
export type Quality = QualityFinding[];
export type Skipped = number;
export type Command = string;
export type Durationseconds1 = number;
export type Logtail = string;
export type Name1 = string;
export type Outcome = "passed" | "failed" | "not-run" | "timed-out";
export type Steps = ToolStep[];
export type Durationseconds2 = number;
export type Id3 = string;
export type Kind2 = "unit" | "api" | "acceptance" | "integration" | "regression";
export type Message = string;
export type Name2 = string;
export type Obsolete = string;
export type Origin = "upstream" | "skeleton" | "filled" | "healed";
export type Outcome1 = "passed" | "failed" | "skipped" | "errored" | "not-run";
export type Sinceversion = number;
export type Criterionid = string;
export type Endpointids = string[];
export type Requirementids = string[];
export type Storyid = string | null;
export type Cases = TestCase[];
export type Failed1 = number;
export type Framework = string;
export type Passed2 = number;
export type Path3 = string;
export type Suites = TestSuite[];
export type Target4 = string;
export type Total1 = number;
/**
 * Tests this component wrote that say nothing about what they came from.
 *
 * The self healing classifier's first signal is what a failing test traces
 * to, so a report full of untraced cases is a report the classifier can say
 * nothing about: every failure comes back `undecided`, which reads like
 * caution and is actually an absence of evidence.
 *
 * It was exactly that, silently, until 2026-09-26. The generation stage
 * wrote the traces and the run stage replaced its report with one built from
 * the runner's output, which knows nothing about stories or criteria, so
 * every executed failure reached the classifier with an empty trace. The
 * loop was never wrong; it just could not answer. A derived count makes that
 * state loud rather than invisible, which is the whole reason it is here.
 *
 * `upstream` cases are excluded and their absence of a trace is not a
 * defect: they came with the repository and were not written from an
 * artefact, so there is nothing for them to point at. Counting them would
 * make this number describe the target rather than the platform.
 */
export type Untraced = number;
export type Version4 = number;
export type At4 = string;
export type Author = string;
export type Content = string;
export type Id4 = string;
export type Kind3 = "user_note" | "answer" | "stage_summary" | "system";
export type Producedversion = number | null;
export type Stageid =
  | ("test-generation" | "test-run" | "test-quality" | "self-healing" | "security-scan" | "remediation" | "test-review")
  | null;
export type Thread = TestThreadMessage[];
export type Approvedat = string | null;
export type Approvedby = string | null;
export type Arm = "scanner" | "llm" | "trained";
export type Completiontokens = number;
export type Costusd = number | null;
export type Durationseconds3 = number;
export type Filesscanned = number;
export type Modelid = string;
export type Offline = boolean;
export type Prompttokens = number;
export type Startedat1 = string;
export type Detectorruns = DetectorRun[];
export type Basescore = number;
export type Confidence = number;
export type Confidencesource = "arm-agreement" | "scanner-rule" | "calibration";
export type Cwe1 = string;
export type Endline = number;
export type Path4 = string;
export type Snippet = string;
export type Startline = number;
export type Explanation = string;
export type Attackcomplexity = "L" | "H";
export type Attackvector = "N" | "A" | "L" | "P";
export type Availability = "N" | "L" | "H";
export type Confidentiality = "N" | "L" | "H";
export type Integrity = "N" | "L" | "H";
export type Privilegesrequired = "N" | "L" | "H";
export type Scope1 = "U" | "C";
export type Userinteraction = "N" | "R";
export type Vector = string;
export type Id5 = string;
export type Origin1 = "scanner" | "llm" | "trained" | "merged";
/**
 * @minItems 1
 */
export type Raisedby = ["scanner" | "llm" | "trained", ...("scanner" | "llm" | "trained")[]];
export type Remediation = string;
export type Runid = string;
export type Severity = "none" | "low" | "medium" | "high" | "critical";
export type Severityreasoning = string;
export type Status1 = "open" | "dismissed" | "fix-proposed" | "re-verifying" | "verified";
export type Title = string;
export type Findings = SecurityFinding[];
export type Generatedat5 = string;
export type Opencriticalorhigh = number;
export type Openfindings2 = number;
export type Refusedcount = number;
export type Claimedpath = string;
export type Claimedstartline = number | null;
export type Cwe2 = string;
export type Detail4 = string;
export type Origin2 = "scanner" | "llm" | "trained";
export type Reason1 =
  "file-not-found" | "span-out-of-range" | "snippet-does-not-match" | "malformed-cwe" | "no-evidence";
export type Refusedevidence = RefusedFinding[];
export type Reportversion = string;
export type Target5 = string;
export type Failed2 = number;
export type Linecoverage1 = number;
export type Mutationscore1 = number | null;
export type Passed3 = number;
export type Run = number;
export type Skipped1 = number;
export type Detail5 = string;
export type Ran = boolean;
export type Tool1 = string;
export type Version5 = string;
export type Tools = ToolOutcome[];
export type Version6 = number;

/**
 * Everything the testing workspace renders, in one read.
 */
export interface TestSnapshot {
  audit: Audit;
  awaitingDecision: Awaitingdecision;
  codeMovedOn: Codemovedon;
  codeVersion: Codeversion;
  findingDecisions: Findingdecisions;
  fixShipsWith: FixShipsWith | null;
  gate: GateState;
  heal: HealReport | null;
  healDecisions: Healdecisions;
  openFindings: Openfindings;
  projectId: Projectid;
  refusedRepairs: Refusedrepairs;
  remediation: RemediationProposals | null;
  run: RunStatus | null;
  stages: Stages;
  target: Target3;
  testVersion: Testversion;
  testedCodeVersion: Testedcodeversion;
  tests: TestReport | null;
  thread: Thread;
  validation: ValidationReport | null;
}
/**
 * One entry in the audit log about this phase, as the report lists it.
 */
export interface TestAuditEntry {
  action: Action;
  actor: Actor;
  at: At;
  detail: Detail;
  target: Target;
}
/**
 * What a person decided about one security finding, newest per finding.
 *
 * Dismissed: it does not apply here, with a note saying why. Accepted: it is
 * real, and with a note, the risk is taken knowingly, so the release gate lets
 * it ship (G8). A decision was recorded and the page never read it back.
 */
export interface FindingDecision {
  at: At1;
  by: By;
  decision: Decision;
  findingId: Findingid;
  note: Note;
}
/**
 * Where a fix applied now lands, when that is newer code than may ship today.
 *
 * A fix patches the newest code version. When the newest approved tests
 * measured an older one, the fix reaches production only together with the
 * rest of the newer version, once its tests are approved: a fix to the older
 * version alone is not offered, so code versions stay one line (review item
 * C4-13).
 */
export interface FixShipsWith {
  codeVersion: Codeversion1;
  releasableCodeVersion: Releasablecodeversion;
  releasableSprint: Releasablesprint;
  sprint: Sprint;
}
export interface GateState {
  decision: GateDecision | null;
  history: History;
}
export interface GateDecision {
  at: At2;
  by: By1;
  kind: Kind;
  note: Note1;
  version: Version;
}
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
  target: Target1;
  toCodeVersion: Tocodeversion;
  version: Version1;
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
  detail: Detail1;
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
/**
 * What a person decided about one failing test, newest per test.
 *
 * About a repair the healing loop made: kept or reverted. The guard decides
 * mechanically whether a repair may be accepted; this is the reader's verdict
 * afterwards, a second fact about the same repair. It was recorded and never
 * read back, so the page changed nothing on a decision.
 *
 * Or about a generated test that fails and that no repair will fix, which
 * could otherwise block a release for good: quarantined (skipped, with the
 * reason above it, until restored) or sent back to be written again (a test
 * that never passed, back to a todo the next run fills).
 */
export interface HealDecision {
  at: At3;
  by: By2;
  decision: Decision1;
  note: Note2;
  testId: Testid1;
}
/**
 * Every proposal one scan produced, as one stored artefact.
 *
 * The artefact kind is `remediation-proposal` because that is what it is
 * about; the body is a set because a scan answers several findings at once
 * and storing one artefact per proposal would put the version axis in a place
 * it does not belong.
 */
export interface RemediationProposals {
  awaitingDecision: Awaitingdecision1;
  generatedAt: Generatedat1;
  proposals: Proposals;
  target: Target2;
  version: Version2;
}
export interface RemediationProposal {
  affectedEndpoints: Affectedendpoints;
  affectedTests: Affectedtests;
  appliedCodeVersion: Appliedcodeversion;
  awaitingDecision: Awaitingdecision2;
  cwe: Cwe;
  decidedAt: Decidedat;
  decidedBy: Decidedby;
  decisionNote: Decisionnote;
  findingId: Findingid1;
  generatedAt: Generatedat2;
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
  diff: Diff1;
  path: Path1;
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
  findingId: Findingid2;
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
  openFindings: Openfindings1;
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
/**
 * The phase's newest full run.
 *
 * A stage retry is a run of its own, and it is not this one: it reports on
 * its own stage, and a retry that finished must not hide the full run beneath
 * it that stopped short of the review.
 */
export interface RunStatus {
  error: Error;
  finishedAt: Finishedat;
  id: Id1;
  model: Model;
  startedAt: Startedat;
  state: State1;
  stoppedAt: Stoppedat;
  thinking: Thinking;
  version: Version3;
}
export interface Stages {
  [k: string]: TestStageState;
}
/**
 * One stage of the testing phase, as the stepper renders it.
 */
export interface TestStageState {
  error: Error1;
  generatedAt: Generatedat3;
  generatedFromVersion: Generatedfromversion;
  id: Id2;
  modelUse: StageModelUse | null;
  status: Status;
  summary: Summary1;
}
/**
 * The model use behind one stage's current version.
 *
 * `answered_by` names the models the responses named, which is what the
 * provider says answered rather than the string the component was configured
 * with. `requests` counts the responses received, output retries included.
 * A stage that asked no model carries none of this.
 */
export interface StageModelUse {
  answeredBy: Answeredby;
  reasoningTokens: Reasoningtokens;
  requests: Requests;
  thinking: Thinking1;
  tokensIn: Tokensin;
  tokensOut: Tokensout;
}
/**
 * One execution of one target's tests.
 *
 * Replaced by the next run rather than accumulated: a heal report outlives
 * it, and the evaluation reads the stamped copies rather than this one.
 */
export interface TestReport {
  branchCoverage: Branchcoverage;
  coverage: Coverage;
  failed: Failed;
  gaps: Gaps;
  generatedAt: Generatedat4;
  isolation: Isolation;
  lineCoverage: Linecoverage;
  mutation: MutationResult | null;
  mutationSkippedReason: Mutationskippedreason;
  notRun: Notrun;
  passed: Passed1;
  quality: Quality;
  skipped: Skipped;
  steps: Steps;
  suites: Suites;
  target: Target4;
  total: Total1;
  untraced: Untraced;
  version: Version4;
}
/**
 * Coverage for one module, with the raw counts kept.
 *
 * Percentages are derived here rather than stored for the same reason the
 * totals are: a percentage without its numerator cannot be added to another
 * one, and the evaluation adds them.
 */
export interface CoverageEntry {
  branchPercent: Branchpercent;
  branchesCovered: Branchescovered;
  branchesTotal: Branchestotal;
  linePercent: Linepercent;
  linesCovered: Linescovered;
  linesTotal: Linestotal;
  module: Module;
}
/**
 * A contract obligation no test can assert, and why.
 *
 * Not a failing test and not an unwritten one. The contract restricts an
 * operation to a role and the application has no sign-in, or declares an
 * operation on a record nothing can create: a test asserting the obligation
 * would fail for ever and say the wrong thing, since the fault is an absent
 * feature. So it is named here, on the report, where the page that says what
 * was generated can say what was not.
 */
export interface TestGap {
  detail: Detail2;
  endpointId: Endpointid;
  kind: Kind1;
}
/**
 * Which mutants died, and which lived to tell the reader something.
 *
 * `scope` is not decoration. Mutation is run over named files rather than the
 * whole workspace, both because this machine cannot afford the whole
 * workspace and because the honesty guard only wants mutants in the region a
 * test exercises. A mutation score means nothing without the set it was
 * measured over, so the set travels with the score.
 *
 * Survivors are listed rather than counted. A survived mutant is a piece of
 * behaviour no test noticed, which is the actionable half of the result, and
 * counting it loses the address.
 */
export interface MutationResult {
  durationSeconds: Durationseconds;
  inconclusive: Inconclusive;
  killed: Killed;
  notMeasured: Notmeasured;
  scope: Scope;
  score: Score;
  survived: Survived;
  tool: Tool;
  total: Total;
}
/**
 * An app in the mutation scope that gave no score, and why.
 *
 * Each app is mutated on its own, as its suite runs, so one can score while
 * another does not. The score is over the apps that did, and this names the
 * rest: until 2026-10-09 every mutant was made in the first scoped file's app,
 * and the other app was never mutated at all (review item C3-6).
 */
export interface UnmeasuredApp {
  app: App;
  reason: Reason;
}
/**
 * One thing wrong with one test, said the way a reviewer would say it.
 *
 * Findings about tests, not about the code under test: a suite can be green
 * and still be worth nothing, and the three most common reasons are a test
 * that asserts nothing, a test that only passes when it runs first, and a
 * test that runs the code and would not notice if it changed. None of them
 * shows up in a pass rate, which is why they are reported separately rather
 * than folded into one.
 *
 * `kills-no-mutant` is the strongest of the three and the only one that needs
 * a mutation run to see. It is named for the observation rather than for the
 * author: the same fact about a test a model wrote is a weak fill, and about
 * a test that came with the repository it is a gap the repository already
 * had. The report counts them per origin so the two stay distinguishable.
 */
export interface QualityFinding {
  detail: Detail3;
  observed: Observed;
  path: Path2;
  rule: Rule;
  test: Test;
}
/**
 * One command the harness ran, and what it did.
 *
 * The same shape as C2's build steps, and for the same reason: a reader who
 * is told the tests failed needs to know whether they failed or never ran.
 */
export interface ToolStep {
  command: Command;
  durationSeconds: Durationseconds1;
  logTail: Logtail;
  name: Name1;
  outcome: Outcome;
}
/**
 * One test file, and what its cases did.
 */
export interface TestSuite {
  cases: Cases;
  failed: Failed1;
  framework: Framework;
  passed: Passed2;
  path: Path3;
}
export interface TestCase {
  durationSeconds: Durationseconds2;
  id: Id3;
  kind: Kind2;
  message: Message;
  name: Name2;
  obsolete: Obsolete;
  origin: Origin;
  outcome: Outcome1;
  sinceVersion: Sinceversion;
  traces: TestTrace;
}
/**
 * What this test was written from. Every reference is an id, never a position.
 *
 * This carried a `criterionIndex` into the story's `acceptance` list until
 * 2026-09-26, on the reasoning that criteria had no ids of their own and
 * inventing them here would be a second source of truth for something C1 owns.
 * C1 owns them now and they survive a regeneration, so the index was the last
 * positional reference left in a trace, and it had the defect every positional
 * reference across versions has: a criterion inserted ahead of another moves
 * what index 0 names, so a test written at one design version traces to a
 * different criterion at the next.
 *
 * The index is dropped rather than kept alongside the id. Two references to the
 * same thing is how the two start disagreeing, which is the argument every
 * count in this file is computed for, and a reader wanting the position can
 * take it from the story's own list.
 */
export interface TestTrace {
  criterionId: Criterionid;
  endpointIds: Endpointids;
  requirementIds: Requirementids;
  storyId: Storyid;
}
export interface TestThreadMessage {
  at: At4;
  author: Author;
  content: Content;
  id: Id4;
  kind: Kind3;
  producedVersion: Producedversion;
  stageId: Stageid;
}
export interface ValidationReport {
  approvedAt: Approvedat;
  approvedBy: Approvedby;
  detectorRuns: Detectorruns;
  findings: Findings;
  generatedAt: Generatedat5;
  openCriticalOrHigh: Opencriticalorhigh;
  openFindings: Openfindings2;
  refusedCount: Refusedcount;
  refusedEvidence: Refusedevidence;
  reportVersion: Reportversion;
  target: Target5;
  tests: TestSummary;
  tools: Tools;
  version: Version6;
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
  durationSeconds: Durationseconds3;
  filesScanned: Filesscanned;
  modelId: Modelid;
  offline: Offline;
  promptTokens: Prompttokens;
  startedAt: Startedat1;
}
export interface SecurityFinding {
  baseScore: Basescore;
  confidence: Confidence;
  confidenceSource: Confidencesource;
  cwe: Cwe1;
  evidence: EvidenceSpan;
  explanation: Explanation;
  factors: CvssFactors;
  id: Id5;
  origin: Origin1;
  raisedBy: Raisedby;
  remediation: Remediation;
  runId: Runid;
  severity: Severity;
  severityReasoning: Severityreasoning;
  status: Status1;
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
  path: Path4;
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
  scope: Scope1;
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
  cwe: Cwe2;
  detail: Detail4;
  origin: Origin2;
  reason: Reason1;
}
/**
 * The test side in one block, so C4 reads one artefact rather than two.
 */
export interface TestSummary {
  failed: Failed2;
  lineCoverage: Linecoverage1;
  mutationScore: Mutationscore1;
  passed: Passed3;
  run: Run;
  skipped: Skipped1;
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
  detail: Detail5;
  ran: Ran;
  tool: Tool1;
  version: Version5;
}

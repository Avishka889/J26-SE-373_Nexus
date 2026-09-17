/**
 * Generated from contracts/*.schema.json. Do not edit by hand.
 *
 * Regenerate with: npm run gen:contracts
 * The schemas themselves are generated from the Pydantic models in
 * packages/contracts-py, which are the single author of every artefact shape.
 */

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
export type Detail = string;
export type Endpointid = string;
export type Kind = string;
export type Gaps = TestGap[];
export type Generatedat = string;
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
export type Passed = number;
export type Detail1 = string;
export type Observed = boolean;
export type Path = string;
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
export type Name = string;
export type Outcome = "passed" | "failed" | "not-run" | "timed-out";
export type Steps = ToolStep[];
export type Durationseconds2 = number;
export type Id = string;
export type Kind1 = "unit" | "api" | "acceptance" | "integration" | "regression";
export type Message = string;
export type Name1 = string;
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
export type Passed1 = number;
export type Path1 = string;
export type Suites = TestSuite[];
export type Target = string;
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
export type Version = number;

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
  generatedAt: Generatedat;
  isolation: Isolation;
  lineCoverage: Linecoverage;
  mutation: MutationResult | null;
  mutationSkippedReason: Mutationskippedreason;
  notRun: Notrun;
  passed: Passed;
  quality: Quality;
  skipped: Skipped;
  steps: Steps;
  suites: Suites;
  target: Target;
  total: Total1;
  untraced: Untraced;
  version: Version;
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
  detail: Detail;
  endpointId: Endpointid;
  kind: Kind;
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
  detail: Detail1;
  observed: Observed;
  path: Path;
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
  name: Name;
  outcome: Outcome;
}
/**
 * One test file, and what its cases did.
 */
export interface TestSuite {
  cases: Cases;
  failed: Failed1;
  framework: Framework;
  passed: Passed1;
  path: Path1;
}
export interface TestCase {
  durationSeconds: Durationseconds2;
  id: Id;
  kind: Kind1;
  message: Message;
  name: Name1;
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

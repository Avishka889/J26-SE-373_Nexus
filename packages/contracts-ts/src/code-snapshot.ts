/**
 * Generated from contracts/*.schema.json. Do not edit by hand.
 *
 * Regenerate with: npm run gen:contracts
 * The schemas themselves are generated from the Pydantic models in
 * packages/contracts-py, which are the single author of every artefact shape.
 */

export type Contractversion = number;
export type Agreementrate = number;
export type Endpointscalled = number;
export type Endpointsimplemented = number;
export type Endpointsmissing = string[];
export type Endpointstotal = number;
export type Endpointsunused = string[];
export type Foreigncalls = string[];
export type Orphanroutes = string[];
export type Schemamismatches = number;
export type Hint = string;
export type Line = number | null;
export type Path = string;
export type Reason = string;
export type Ruleid = string;
export type Severity = "error" | "warning";
export type Subject = string;
export type Findings = AgreementFinding[];
export type Approvedthrough = number | null;
export type Codeversion = number;
export type Chosen = "rule" | "llm" | "merged";
/**
 * Canonical keys both arms produced.
 */
export type Agreed = string[];
export type Agreementrate1 = number;
/**
 * Canonical "METHOD /path".
 */
export type Endpointkey = string;
export type Field = string;
export type Llmvalue = string;
export type Rulevalue = string;
export type Conflicts = ContractConflict[];
export type Attempts = number;
export type Endpoints = number;
export type Errors = number;
export type Warnings = number;
export type Llmonly = string[];
export type Ruleonly = string[];
export type Authactors = string[];
export type Confidence = number;
export type Id = string;
export type Method = "GET" | "POST" | "PUT" | "PATCH" | "DELETE";
export type Origin = "rule" | "llm" | "merged";
export type Path1 = string;
export type Entity = string;
export type Itemref = string;
export type Maxlength = number | null;
export type Maximum = number | null;
export type Minlength = number | null;
export type Minimum = number | null;
export type Name = string;
export type Oneof = string[];
export type Required = boolean;
export type Rules = string[];
export type Type = "string" | "number" | "boolean" | "date" | "id" | "object" | "array";
export type Fields = SchemaField[];
export type Summary = string;
export type Actionids = string[];
export type Requirementids = string[];
export type Screenids = string[];
export type Storyids = string[];
export type Validation = string[];
export type Endpoints1 = ApiEndpoint[];
export type Fields1 = SchemaField[];
export type Name1 = string;
export type Traces = string[];
export type Entities = EntityModel[];
export type Version = number;
export type Llmfailure = string | null;
export type Reason1 = string;
export type Ruleid1 = string;
export type Severity1 = "error" | "warning";
export type Subject1 = string;
export type Rulefindings = ContractRuleFinding[];
export type Version1 = number;
export type Designblocker = string | null;
export type Designversion = number;
/**
 * Endpoint ids new in `to`.
 */
export type Added = string[];
export type After = string;
export type Before = string;
export type Endpointid = string;
export type Field1 = string;
export type Changed = EndpointChange[];
export type Fromversion = number;
export type Removed = string[];
export type Toversion = number;
export type At = string;
export type By = string;
export type Kind = "approved" | "changes";
export type Note = string | null;
export type Version2 = number;
export type History = GateDecision[];
export type Generatedfromdesignversion = number;
export type Number = number;
export type Points = number;
export type Id1 = string;
export type Points1 = number;
export type Priority = "must" | "should" | "could";
export type Title = string;
export type Stories = NextSprintStory[];
export type Velocity = number;
export type Velocitybasis = string;
export type Projectid = string;
export type Isolation = string;
/**
 * @minItems 1
 */
export type Steps = [BuildStepReport, ...BuildStepReport[]];
export type Command = string;
export type Durationseconds = number | null;
export type Logtail = string;
export type Name2 = string;
export type Outcome = "passed" | "failed" | "not-run" | "timed-out";
export type Toolchain = string;
export type Arm = "rule" | "llm" | "merged";
export type Carriedfixes = number[];
export type Generator = "static" | "rule" | "model";
export type Implements = string[];
export type Path2 = string;
export type Reusedfromversion = number;
export type Stage = string;
export type Summary1 = string;
export type Writtenfrom = string;
export type Manifest = ManifestRow[];
export type Notpushedreason = string | null;
export type Branch = string;
export type Commitsha = string;
export type Defaultbranch = string;
export type Name3 = string;
export type Owner = string;
export type Provider = "github";
export type Pullrequestnumber = number | null;
export type Pullrequesturl = string;
export type Url = string;
export type Version3 = number;
export type Error = string | null;
export type Finishedat = string | null;
export type Id2 = string;
export type Model = string | null;
export type Startedat = string;
export type State = "queued" | "running" | "awaiting_gate" | "done" | "failed" | "superseded";
export type Stoppedat = string | null;
export type Thinking = string | null;
export type Version4 = number;
export type Sprintname = string;
export type Decidedby = string;
export type Id3 = string;
export type Inscope = boolean;
export type Points2 = number;
export type Sprint = number;
export type Title1 = string;
export type Requirementids1 = string[];
export type Screenids1 = string[];
export type Stories1 = ScopeStory[];
export type Error1 = string | null;
export type Generatedat = string | null;
export type Generatedfromversion = number;
export type Id4 =
  | "sprint-scope"
  | "tech-stack"
  | "api-contract"
  | "frontend-code"
  | "backend-code"
  | "contract-agreement"
  | "build"
  | "code-review";
/**
 * @minItems 1
 */
export type Answeredby = [string, ...string[]];
export type Reasoningtokens = number;
export type Requests = number;
export type Thinking1 = string[];
export type Tokensin = number;
export type Tokensout = number;
export type Status = "pending" | "generating" | "complete" | "failed";
export type Summary2 = string | null;
/**
 * @minItems 1
 */
export type Candidates = [StackCandidate, ...StackCandidate[]];
export type Available = boolean;
export type Explanation = string;
export type Id5 = string;
/**
 * @minItems 1
 */
export type Layers = [StackLayer, ...StackLayer[]];
export type Choice = string;
export type Name4 = string;
export type Rationale = string;
export type Version5 = string;
export type Name5 = string;
export type Score = number;
export type Label = string;
export type Points3 = number;
export type Scorebreakdown = ScorePart[];
export type Unavailablereason = string | null;
export type Label1 = string;
export type Value = number;
export type Facts = CountedFact[];
export type Recommendedid = string;
export type Selectedat = string | null;
export type Selectedby = string | null;
export type Selectedid = string | null;
export type At1 = string;
export type Author = string;
export type Content = string;
export type Id6 = string;
export type Kind1 = "user_note" | "answer" | "stage_summary" | "system";
export type Producedversion = number | null;
export type Stageid =
  | (
      | "sprint-scope"
      | "tech-stack"
      | "api-contract"
      | "frontend-code"
      | "backend-code"
      | "contract-agreement"
      | "build"
      | "code-review"
    )
  | null;
export type Thread = CodeThreadMessage[];

export interface CodeSnapshot {
  agreement: ContractAgreement | null;
  approvedThrough: Approvedthrough;
  codeVersion: Codeversion;
  contract: ApiContractArtefact | null;
  designBlocker: Designblocker;
  designVersion: Designversion;
  diff: ContractDiff | null;
  gate: GateState;
  generatedFromDesignVersion: Generatedfromdesignversion;
  nextSprint: NextSprint | null;
  projectId: Projectid;
  repository: CodeRepository | null;
  run: RunStatus | null;
  scope: SprintScope | null;
  stages: Stages;
  techStack: TechStackArtefact | null;
  thread: Thread;
}
export interface ContractAgreement {
  contractVersion: Contractversion;
  counts: AgreementCounts;
  findings: Findings;
}
export interface AgreementCounts {
  agreementRate: Agreementrate;
  endpointsCalled: Endpointscalled;
  endpointsImplemented: Endpointsimplemented;
  endpointsMissing: Endpointsmissing;
  endpointsTotal: Endpointstotal;
  endpointsUnused: Endpointsunused;
  foreignCalls: Foreigncalls;
  orphanRoutes: Orphanroutes;
  schemaMismatches: Schemamismatches;
}
export interface AgreementFinding {
  hint: Hint;
  location: CodeLocation | null;
  reason: Reason;
  ruleId: Ruleid;
  severity: Severity;
  subject: Subject;
}
export interface CodeLocation {
  line: Line;
  path: Path;
}
/**
 * The stored artefact: both arms, the comparison, and the choice.
 *
 * `contract` is the effective one downstream stages generate from. It equals
 * the chosen arm's output, or the recorded merge. The losing arm is kept
 * whole, because the evaluation compares arms and an artefact that kept only
 * the winner would have destroyed its own denominator.
 */
export interface ApiContractArtefact {
  chosen: Chosen;
  comparison: ArmComparison | null;
  contract: ApiContract;
  llmArm: ApiContract | null;
  llmFailure: Llmfailure;
  ruleArm: ApiContract;
  ruleFindings: Rulefindings;
  version: Version1;
}
/**
 * The ablation data, one run's worth.
 */
export interface ArmComparison {
  agreed: Agreed;
  agreementRate: Agreementrate1;
  conflicts: Conflicts;
  llm: ArmCounts;
  llmOnly: Llmonly;
  rule: ArmCounts;
  ruleOnly: Ruleonly;
}
/**
 * The same endpoint, said differently by the two arms. Surfaced as a
 * finding and decided item by item when the human picks merged.
 */
export interface ContractConflict {
  endpointKey: Endpointkey;
  field: Field;
  llmValue: Llmvalue;
  ruleValue: Rulevalue;
}
export interface ArmCounts {
  attempts: Attempts;
  endpoints: Endpoints;
  errors: Errors;
  warnings: Warnings;
}
/**
 * The effective contract one arm produced, or the human's merge.
 */
export interface ApiContract {
  endpoints: Endpoints1;
  entities: Entities;
  version: Version;
}
export interface ApiEndpoint {
  authActors: Authactors;
  confidence: Confidence;
  id: Id;
  method: Method;
  origin: Origin;
  path: Path1;
  request: EndpointSchema | null;
  response: EndpointSchema | null;
  summary: Summary;
  traces: EndpointTraces;
  validation: Validation;
}
/**
 * A request or response body, as fields plus the entity it derives from.
 */
export interface EndpointSchema {
  entity: Entity;
  fields: Fields;
}
export interface SchemaField {
  itemRef: Itemref;
  maxLength: Maxlength;
  maximum: Maximum;
  minLength: Minlength;
  minimum: Minimum;
  name: Name;
  oneOf: Oneof;
  required: Required;
  rules: Rules;
  type: Type;
}
/**
 * Where an endpoint comes from. The unit of inference is the user action
 * on a screen, so screens and actions lead; stories and requirements ground
 * them in the plan and the brief.
 */
export interface EndpointTraces {
  actionIds: Actionids;
  requirementIds: Requirementids;
  screenIds: Screenids;
  storyIds: Storyids;
}
/**
 * A data shape the schemas reference, derived from a graph entity.
 */
export interface EntityModel {
  fields: Fields1;
  name: Name1;
  traces: Traces;
}
/**
 * One of the rule catalogue's findings about an arm's contract.
 */
export interface ContractRuleFinding {
  reason: Reason1;
  ruleId: Ruleid1;
  severity: Severity1;
  subject: Subject1;
}
/**
 * What moved between two contract versions: the agile mechanic's receipt.
 */
export interface ContractDiff {
  added: Added;
  changed: Changed;
  fromVersion: Fromversion;
  removed: Removed;
  toVersion: Toversion;
}
export interface EndpointChange {
  after: After;
  before: Before;
  endpointId: Endpointid;
  field: Field1;
}
export interface GateState {
  decision: GateDecision | null;
  history: History;
}
export interface GateDecision {
  at: At;
  by: By;
  kind: Kind;
  note: Note;
  version: Version2;
}
/**
 * What planning the next sprint would add to the build, shown before anyone asks.
 *
 * Divided as the sprint plan divides one: the stories out of the build in
 * priority order, up to the velocity assumption, stopping at the first that
 * does not fit. Empty when every story is in the build.
 */
export interface NextSprint {
  number: Number;
  points: Points;
  stories: Stories;
  velocity: Velocity;
  velocityBasis: Velocitybasis;
}
export interface NextSprintStory {
  id: Id1;
  points: Points1;
  priority: Priority;
  title: Title;
}
export interface CodeRepository {
  build: BuildReport | null;
  manifest: Manifest;
  notPushedReason: Notpushedreason;
  repository: RepositoryPointer | null;
  version: Version3;
}
export interface BuildReport {
  isolation: Isolation;
  steps: Steps;
  toolchain: Toolchain;
}
export interface BuildStepReport {
  command: Command;
  durationSeconds: Durationseconds;
  logTail: Logtail;
  name: Name2;
  outcome: Outcome;
}
export interface ManifestRow {
  arm: Arm;
  carriedFixes: Carriedfixes;
  generator: Generator;
  implements: Implements;
  path: Path2;
  reusedFromVersion: Reusedfromversion;
  stage: Stage;
  summary: Summary1;
  writtenFrom: Writtenfrom;
}
export interface RepositoryPointer {
  branch: Branch;
  commitSha: Commitsha;
  defaultBranch: Defaultbranch;
  name: Name3;
  owner: Owner;
  provider: Provider;
  pullRequestNumber: Pullrequestnumber;
  pullRequestUrl: Pullrequesturl;
  url: Url;
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
  id: Id2;
  model: Model;
  startedAt: Startedat;
  state: State;
  stoppedAt: Stoppedat;
  thinking: Thinking;
  version: Version4;
}
export interface SprintScope {
  sprintName: Sprintname;
  stories: Stories1;
}
/**
 * One story's place in the build: in or out, and why it maps anywhere.
 */
export interface ScopeStory {
  decidedBy: Decidedby;
  id: Id3;
  inScope: Inscope;
  points: Points2;
  sprint: Sprint;
  title: Title1;
  traces: ScopeStoryTraces;
}
export interface ScopeStoryTraces {
  requirementIds: Requirementids1;
  screenIds: Screenids1;
}
export interface Stages {
  [k: string]: CodeStageState;
}
export interface CodeStageState {
  error: Error1;
  generatedAt: Generatedat;
  generatedFromVersion: Generatedfromversion;
  id: Id4;
  modelUse: StageModelUse | null;
  status: Status;
  summary: Summary2;
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
export interface TechStackArtefact {
  candidates: Candidates;
  facts: Facts;
  recommendedId: Recommendedid;
  selectedAt: Selectedat;
  selectedBy: Selectedby;
  selectedId: Selectedid;
}
export interface StackCandidate {
  available: Available;
  explanation: Explanation;
  id: Id5;
  layers: Layers;
  name: Name5;
  score: Score;
  scoreBreakdown: Scorebreakdown;
  unavailableReason: Unavailablereason;
}
export interface StackLayer {
  choice: Choice;
  name: Name4;
  rationale: Rationale;
  version: Version5;
}
export interface ScorePart {
  label: Label;
  points: Points3;
}
/**
 * One number the scoring rests on, named so a reader can check it.
 */
export interface CountedFact {
  label: Label1;
  value: Value;
}
export interface CodeThreadMessage {
  at: At1;
  author: Author;
  content: Content;
  id: Id6;
  kind: Kind1;
  producedVersion: Producedversion;
  stageId: Stageid;
}

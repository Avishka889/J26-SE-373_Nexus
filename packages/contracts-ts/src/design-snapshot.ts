/**
 * Generated from contracts/*.schema.json. Do not edit by hand.
 *
 * Regenerate with: npm run gen:contracts
 * The schemas themselves are generated from the Pydantic models in
 * packages/contracts-py, which are the single author of every artefact shape.
 */

export type Appname = string;
/**
 * @minItems 2
 */
export type Candidates = [TopologyCandidate, TopologyCandidate, ...TopologyCandidate[]];
/**
 * @minItems 2
 */
export type Cons = [string, string, ...string[]];
export type Id = string;
export type Name = string;
/**
 * @minItems 1
 */
export type Pros = [string, ...string[]];
export type Rationale = string;
export type Score = number;
export type Recommendedcandidateid = string;
export type Selectedat = string | null;
export type Selectedby = string | null;
export type Selectedcandidateid = string | null;
export type Id1 = string;
export type Name1 = string;
export type Note = string;
export type Dismissed = boolean;
export type Edited = boolean;
export type Id2 = string;
export type Text = string;
export type Traces = string[];
export type Assumptions = Assumption[];
export type Fromversion = number;
export type Added = string[];
export type After = string;
export type Before = string;
export type Field = string;
export type Requirementid = string;
export type Changed = RequirementChange[];
export type Fromversion1 = number;
export type Removed = string[];
export type Toversion = number;
export type Added1 = string[];
export type Changed1 = string[];
export type Removed1 = string[];
export type Reason = string;
export type Ruleid = string;
export type Severity = "error" | "warning";
export type Stageid =
  | (
      | "requirements"
      | "domain-model"
      | "architecture-graph"
      | "architecture-recommendation"
      | "uml-diagrams"
      | "wireframes"
      | "sprint-plan"
      | "design-review"
    )
  | null;
export type Traces1 = string[];
export type Consistency = ConsistencyFinding[];
export type At = string;
export type By = string;
export type Kind = "approved" | "changes";
export type Note1 = string | null;
export type Version = number;
export type History = GateDecision[];
export type Changednodeids = string[];
export type Id3 = string;
export type Kind1 = "action" | "data" | "dependency" | "constraint";
export type Source = string;
export type Target = string;
export type Traces2 = string[];
export type Verb = string;
export type Edges = GraphEdge[];
export type Actorkind = ("primary" | "external_system") | null;
export type Appliesto = string[];
export type Name2 = string;
export type Type = string;
export type Attributes = EntityAttribute[];
export type Changedinversion = number | null;
export type Description = string;
export type Id4 = string;
export type Kind2 = "actor" | "entity" | "service" | "constraint";
export type Label = string;
export type X = number;
export type Y = number;
export type Standard = string | null;
export type Traces3 = string[];
export type Reason1 = string;
export type Ruleid1 = string;
export type Traces4 = string[];
export type Nodes = GraphNode[];
export type Projectid = string;
export type Answer = string | null;
export type Answeredat = string | null;
export type Id5 = string;
export type Question = string;
export type Traces5 = string[];
export type Questions = ClarifyingQuestion[];
export type Questionspending = boolean;
export type Queuedchanges = string[];
export type Adjusted = boolean;
export type Confidence = number;
export type Id6 = string;
export type Lowconfidence = boolean;
export type Priority = "must" | "should" | "could";
export type Prioritycorrected = boolean;
export type Qualityattribute = ("performance" | "security" | "usability" | "reliability") | null;
export type Setasidecorrection = string | null;
export type Sourcequote = string | null;
export type Text1 = string;
export type Type1 = "functional" | "quality" | "constraint";
export type Requirements = ParsedRequirement[];
export type Requirementsversion = number;
export type Error = string | null;
export type Finishedat = string | null;
export type Id7 = string;
export type Model = string | null;
export type Startedat = string;
export type State = "queued" | "running" | "awaiting_gate" | "done" | "failed" | "superseded";
export type Stoppedat = string | null;
export type Thinking = string | null;
export type Version1 = number;
/**
 * @minItems 1
 */
export type Acceptance = [AcceptanceCriterion, ...AcceptanceCriterion[]];
export type Given = string;
export type Id8 = string;
export type Then = string;
export type When = string;
export type Epic = string;
export type Id9 = string;
export type Points = number;
export type Priority1 = "must" | "should" | "could";
export type Title = string;
export type Traces6 = string[];
export type Backlog = UserStory[];
export type Because = string;
export type Needs = string;
export type Storyid = string;
export type Backlogdependencies = BacklogDependency[];
export type Estimatedpoints = number;
export type Goal = string;
export type Proposed = UserStory[];
export type Sprintname = string;
export type Basis = string;
export type Points1 = number;
export type Error1 = string | null;
export type Generatedat = string | null;
export type Generatedfromversion = number;
export type Id10 =
  | "requirements"
  | "domain-model"
  | "architecture-graph"
  | "architecture-recommendation"
  | "uml-diagrams"
  | "wireframes"
  | "sprint-plan"
  | "design-review";
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
export type Summary = string | null;
export type At1 = string;
export type Author = string;
export type Content = string;
export type Id11 = string;
export type Kind3 = "user_note" | "answer" | "stage_summary" | "system";
export type Producedversion = number | null;
export type Askedat = string;
export type Id12 = string;
export type Question1 = string;
export type Traces7 = string[];
export type Stageid1 =
  | (
      | "requirements"
      | "domain-model"
      | "architecture-graph"
      | "architecture-recommendation"
      | "uml-diagrams"
      | "wireframes"
      | "sprint-plan"
      | "design-review"
    )
  | null;
export type Thread = DesignThreadMessage[];
export type Description1 = string;
export type Id13 = string;
export type Kind4 = "class" | "er" | "activity" | "sequence";
/**
 * Authored diagram text, when there is any. Null means the diagram is projected from the architecture graph when it is drawn, which is the case for class and entity relationship diagrams: freezing their text here would keep an old name after a node is renamed.
 */
export type Source1 = string | null;
export type Title1 = string;
export type Traces8 = string[];
/**
 * The use case this diagram draws, for sequence diagrams.
 */
export type Usecaseid = string | null;
export type Diagrams = UmlDiagram[];
export type Id14 = string;
export type Name3 = string;
/**
 * @minItems 1
 */
export type Steps = [SequenceStep, ...SequenceStep[]];
/**
 * Id of the architecture graph node this step goes from.
 */
export type Fromid = string;
/**
 * call for a request, return for an answer, note for an aside.
 */
export type Kind5 = "call" | "return" | "note";
/**
 * What is asked or answered. Names inside the text are written as `{nodeId}` tokens, referring to nodes of the architecture graph, and are replaced with the node's current label when the diagram is drawn. Never write a node's name in as text: the copy would not follow a rename. A token naming no node renders as the literal braces, which is deliberate, since a silently dropped name reads as correct.
 */
export type Message = string;
/**
 * Id of the architecture graph node this step goes to.
 */
export type Toid = string;
export type Storyid1 = string | null;
export type Traces9 = string[];
export type Usecases = UseCase[];
export type Covered = boolean;
export type Needsscreen = boolean;
export type Screenids = string[];
export type Storyid2 = string;
export type Storytitle = string;
export type Coverage = WireframeCoverageRow[];
export type Coversstoryids = string[];
export type Id15 = string;
export type Name4 = string;
export type Pendingrefinement = boolean;
export type Refinementnote = string | null;
/**
 * The screens of this flow. The first is the entry point: the player opens there and the card thumbnail shows it, so ordering is meaning rather than presentation. Every other screen has to be reachable from it by following links.
 *
 * @minItems 1
 */
export type Screens = [FlowScreen, ...FlowScreen[]];
export type Id16 = string;
export type Kind6 = "field" | "row" | "summary" | "banner" | "text" | "list" | "button" | "display";
export type Label1 = string;
export type Linkid = string | null;
export type Tone = ("neutral" | "positive" | "muted") | null;
export type Value = string | null;
export type Blocks = ScreenBlock[];
export type Crumbs = string[];
export type Id17 = string;
export type Id18 = string;
export type Label2 = string;
export type Targetid = string;
export type Variant = "primary" | "secondary" | "row" | "text";
export type Links = FlowLink[];
export type Name5 = string;
/**
 * True when this screen is meant to be the end of the journey, such as a confirmation or an error. A screen with no outgoing links is otherwise reported as a dead end, and this is how a flow says the dead end was the point. Assigned by rule from the screen's name and correctable by a human, never written by a generating model: a flag that silences a warning is a flag a model will set to silence the warning.
 */
export type Terminal = boolean;
export type Traces10 = string[];
export type Version2 = string;
export type Flows = WireframeFlow[];

export interface DesignSnapshot {
  appName: Appname;
  architecture: ArchitectureRecommendation | null;
  assumptions: Assumptions;
  changes: DesignChanges | null;
  consistency: Consistency;
  gate: GateState;
  graph: ArchitectureGraph;
  projectId: Projectid;
  questions: Questions;
  questionsPending: Questionspending;
  queuedChanges: Queuedchanges;
  requirements: Requirements;
  requirementsVersion: Requirementsversion;
  run: RunStatus | null;
  sprint: SprintPlan | null;
  stages: Stages;
  thread: Thread;
  uml: UmlArtefact;
  wireframes: WireframesArtefact;
}
export interface ArchitectureRecommendation {
  candidates: Candidates;
  recommendedCandidateId: Recommendedcandidateid;
  selectedAt: Selectedat;
  selectedBy: Selectedby;
  selectedCandidateId: Selectedcandidateid;
  style: ArchitectureStyleNote;
}
export interface TopologyCandidate {
  cons: Cons;
  id: Id;
  name: Name;
  pros: Pros;
  rationale: Rationale;
  score: Score;
}
/**
 * A code organisation style: applies inside whichever shape is chosen.
 */
export interface ArchitectureStyleNote {
  id: Id1;
  name: Name1;
  note: Note;
}
export interface Assumption {
  dismissed: Dismissed;
  edited: Edited;
  id: Id2;
  text: Text;
  traces: Traces;
}
/**
 * What this design version changed since the one before it.
 *
 * A change note regenerates the design, and the review showed the new version
 * with nothing saying what had moved (review item C1-6).
 */
export interface DesignChanges {
  fromVersion: Fromversion;
  requirements: RequirementDiff;
  stories: StoryDiff;
}
/**
 * What moved between two requirements versions.
 *
 * The sibling of `ContractDiff`, and here for the same reason it is: the
 * self healing classifier's first signal is whether the thing a failing test
 * traces to changed between the two versions, and requirements are half of
 * what a test traces to. Endpoints are the other half.
 *
 * A human edit counts as a change. An overlay that rewrote a requirement is
 * exactly the case where a test encoding the old wording is stale rather than
 * right, which is the distinction the whole loop turns on.
 */
export interface RequirementDiff {
  added: Added;
  changed: Changed;
  fromVersion: Fromversion1;
  removed: Removed;
  toVersion: Toversion;
}
/**
 * One requirement that reads differently than it did.
 */
export interface RequirementChange {
  after: After;
  before: Before;
  field: Field;
  requirementId: Requirementid;
}
/**
 * The stories one plan added, dropped or changed against the one before, by id.
 */
export interface StoryDiff {
  added: Added1;
  changed: Changed1;
  removed: Removed1;
}
/**
 * Something two artefacts disagree about, for the reader at the gate.
 *
 * Separate from `ValidationFinding`, which is carried on a single node and says
 * that one thing could not be confirmed. This is about the design as a whole:
 * a must-have with no story, a diagram naming a node the graph no longer has.
 * Neither can be seen from inside the artefact it concerns, and both are read
 * at the moment somebody decides whether to approve.
 *
 * Derived at read time and never stored. It is a statement about the current
 * set of artefacts, so a stored copy would go stale exactly when it mattered:
 * the moment one of them is regenerated.
 */
export interface ConsistencyFinding {
  reason: Reason;
  ruleId: Ruleid;
  severity: Severity;
  stageId: Stageid;
  traces: Traces1;
}
export interface GateState {
  decision: GateDecision | null;
  history: History;
}
export interface GateDecision {
  at: At;
  by: By;
  kind: Kind;
  note: Note1;
  version: Version;
}
export interface ArchitectureGraph {
  changedNodeIds: Changednodeids;
  edges: Edges;
  nodes: Nodes;
}
export interface GraphEdge {
  id: Id3;
  kind: Kind1;
  source: Source;
  target: Target;
  traces: Traces2;
  verb: Verb;
}
export interface GraphNode {
  actorKind: Actorkind;
  appliesTo: Appliesto;
  attributes: Attributes;
  changedInVersion: Changedinversion;
  description: Description;
  id: Id4;
  kind: Kind2;
  label: Label;
  position: Position;
  standard: Standard;
  traces: Traces3;
  unconfirmed: ValidationFinding | null;
}
export interface EntityAttribute {
  name: Name2;
  type: Type;
}
export interface Position {
  x: X;
  y: Y;
}
/**
 * A named rule check that could not confirm a node.
 *
 * Carried on the node itself rather than reported in a separate list, because a
 * warning the reader cannot trace to a cause is worse than no warning: the
 * canvas has to be able to say which rule fired, in plain words, and which
 * requirement the reader should go and look at.
 *
 * `rule_id` is the stable name of one of C1's rule checks, so the same finding
 * can be counted across runs for the evaluation. `reason` is written for the
 * person reading the design, and doubles as the repair hint the extraction loop
 * feeds back to the model.
 */
export interface ValidationFinding {
  reason: Reason1;
  ruleId: Ruleid1;
  traces: Traces4;
}
export interface ClarifyingQuestion {
  answer: Answer;
  answeredAt: Answeredat;
  id: Id5;
  question: Question;
  traces: Traces5;
}
export interface ParsedRequirement {
  adjusted: Adjusted;
  confidence: Confidence;
  id: Id6;
  lowConfidence: Lowconfidence;
  priority: Priority;
  priorityCorrected: Prioritycorrected;
  qualityAttribute: Qualityattribute;
  setAsideCorrection: Setasidecorrection;
  sourceQuote: Sourcequote;
  text: Text1;
  type: Type1;
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
  id: Id7;
  model: Model;
  startedAt: Startedat;
  state: State;
  stoppedAt: Stoppedat;
  thinking: Thinking;
  version: Version1;
}
export interface SprintPlan {
  backlog: Backlog;
  backlogDependencies: Backlogdependencies;
  estimatedPoints: Estimatedpoints;
  goal: Goal;
  proposed: Proposed;
  sprintName: Sprintname;
  velocityAssumption: VelocityAssumption;
}
export interface UserStory {
  acceptance: Acceptance;
  epic: Epic;
  id: Id9;
  points: Points;
  priority: Priority1;
  title: Title;
  traces: Traces6;
}
export interface AcceptanceCriterion {
  given: Given;
  id: Id8;
  then: Then;
  when: When;
}
/**
 * A story in the sprint that needs one left in the backlog.
 *
 * Read off the design: a requirement the sprint's story realises draws a
 * connection to something nothing in the sprint builds, and a backlog story
 * builds it. The sprint is divided by priority and size alone, so nothing else
 * would say that it cannot be finished as proposed (review item C1-5).
 */
export interface BacklogDependency {
  because: Because;
  needs: Needs;
  storyId: Storyid;
}
export interface VelocityAssumption {
  basis: Basis;
  points: Points1;
}
export interface Stages {
  [k: string]: StageState;
}
export interface StageState {
  error: Error1;
  generatedAt: Generatedat;
  generatedFromVersion: Generatedfromversion;
  id: Id10;
  modelUse: StageModelUse | null;
  status: Status;
  summary: Summary;
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
export interface DesignThreadMessage {
  at: At1;
  author: Author;
  content: Content;
  id: Id11;
  kind: Kind3;
  producedVersion: Producedversion;
  question: AskedQuestion | null;
  stageId: Stageid1;
}
/**
 * The question an answer in the conversation answers, as the design asked it.
 */
export interface AskedQuestion {
  askedAt: Askedat;
  id: Id12;
  question: Question1;
  traces: Traces7;
}
export interface UmlArtefact {
  diagrams: Diagrams;
  useCases: Usecases;
}
export interface UmlDiagram {
  description: Description1;
  id: Id13;
  kind: Kind4;
  source: Source1;
  title: Title1;
  traces: Traces8;
  useCaseId: Usecaseid;
}
export interface UseCase {
  id: Id14;
  name: Name3;
  steps: Steps;
  storyId: Storyid1;
  traces: Traces9;
}
export interface SequenceStep {
  fromId: Fromid;
  kind: Kind5;
  message: Message;
  toId: Toid;
}
export interface WireframesArtefact {
  coverage: Coverage;
  flows: Flows;
}
export interface WireframeCoverageRow {
  covered: Covered;
  needsScreen: Needsscreen;
  screenIds: Screenids;
  storyId: Storyid2;
  storyTitle: Storytitle;
}
export interface WireframeFlow {
  coversStoryIds: Coversstoryids;
  id: Id15;
  name: Name4;
  pendingRefinement: Pendingrefinement;
  refinementNote: Refinementnote;
  screens: Screens;
  traces: Traces10;
  version: Version2;
}
export interface FlowScreen {
  blocks: Blocks;
  crumbs: Crumbs;
  id: Id17;
  links: Links;
  name: Name5;
  terminal: Terminal;
}
export interface ScreenBlock {
  id: Id16;
  kind: Kind6;
  label: Label1;
  linkId: Linkid;
  tone: Tone;
  value: Value;
}
export interface FlowLink {
  id: Id18;
  label: Label2;
  targetId: Targetid;
  variant: Variant;
}

/**
 * Generated from contracts/*.schema.json. Do not edit by hand.
 *
 * Regenerate with: npm run gen:contracts
 * The schemas themselves are generated from the Pydantic models in
 * packages/contracts-py, which are the single author of every artefact shape.
 */

export type Analysedtestversion = number;
export type Approvedtestversion = number;
export type Approvedtestedcodeversion = number;
export type Autodeploylow = boolean;
export type Awaitingdecision = number;
export type Code = string;
export type Message = string;
export type Updateid = string | null;
export type Blocking = Blocker[];
export type Candidatehash = string;
export type Codeversion = number;
export type Detail = string;
export type Reason = "rejected" | "deferred" | "no-restore-target" | "superseded" | "out-of-scope";
export type Updateid1 = string;
export type Excluded = ExcludedUpdate[];
export type Fingerprint = string | null;
export type Generatedat = string;
export type Image = string;
export type Imagedigest = string | null;
export type Included = string[];
export type Isolation = string;
export type Lockfilesha256 = string | null;
export type Detail1 = string;
export type Method = "GET";
export type Ok = boolean;
export type Path = string;
export type Statuscode = number | null;
export type Smoke = SmokeCheck[];
/**
 * @minItems 1
 */
export type Steps = [BuildStepReport, ...BuildStepReport[]];
export type Command = string;
export type Durationseconds = number | null;
export type Logtail = string;
export type Name = string;
export type Outcome = "passed" | "failed" | "not-run" | "timed-out";
export type Toolchain = string;
export type Verified = boolean;
export type Version = number;
export type Claimsrefused = number;
export type Claimsverified = number;
export type Generatedat1 = string;
export type Modelid = string;
export type Id = string;
export type Kind = "breaking" | "removal" | "behavioural" | "deprecation" | "security" | "fix" | "feature" | "other";
export type Quote = string;
export type Sourceurl = string;
export type Symbols = string[];
export type Version1 = string;
export type Claims = ChangelogClaim[];
export type Completiontokens = number;
export type Durationseconds1 = number;
export type Error = string;
export type Modelid1 = string;
export type Outcome1 = "answered" | "malformed" | "cut-off" | "rate-limited" | "provider-error";
export type Promptid = string;
export type Promptsha256 = string;
export type Prompttokens = number;
export type Requests = number;
export type Maxtokens = number | null;
export type Temperature = number | null;
export type Thinking = string | null;
export type Statedlevel = ("low" | "medium" | "high") | null;
export type Notesfound = boolean;
export type Detail2 = string;
export type Kind1 = string;
export type Quote1 = string;
export type Reason1 =
  "quote-not-found" | "outside-version-window" | "empty-quote" | "symbol-not-in-quote" | "no-such-source";
export type Symbols1 = string[];
export type Version2 = string;
export type Refused = RefusedClaim[];
export type Updateid2 = string;
export type Abstainedreason = string;
export type Evidenceids = string[];
export type Level = ("low" | "medium" | "high") | null;
export type Rationale = string;
export type Ruleid = string;
export type Signal = "semver" | "changelog" | "usage";
export type Windows = string[];
export type Perupdate = ChangelogAnalysis[];
export type Promptid1 = string;
export type Promptsha2561 = string;
export type Refusalrate = number;
export type Ruleid1 = "changelog-rule/1";
export type Stopreason = string;
export type Stoppedonratelimit = boolean;
export type Version3 = number;
export type Createdat = string;
export type Cluster = string;
export type Database = string;
export type Host = string;
export type Serviceid = string;
export type Username = string;
export type Dashboardurl = string;
export type Name1 = string;
export type Origin = string;
export type Ownerid = string;
export type Serviceid1 = string;
export type Name2 = string;
export type Orgid = string;
export type Origin1 = string;
export type Projectid = string;
/**
 * Whether code newer than what this phase's artefacts describe has approved tests.
 *
 * Newer code without approved tests is not a move: what these artefacts
 * describe is still what may ship.
 */
export type Codemovedon = boolean;
export type Codeversion1 = number;
export type Candidatehash1 = string;
export type Commitsha = string | null;
export type Deployversion = number;
export type Deploymentid = string;
export type Imagedigest1 = string | null;
export type Lockfilesha2561 = string | null;
export type Renderdeployid = string | null;
export type Target = "local" | "cloud";
export type Url = string | null;
export type Verceldeploymentid = string | null;
export type Verifiedat = string;
export type At = string | null;
export type By = string | null;
export type Decision = ("approved" | "rejected" | "deferred") | null;
export type Levelatdecision = ("low" | "medium" | "high") | null;
export type Needsdecision = boolean;
export type Needsreviewnote = boolean;
export type Note = string | null;
export type Updateid3 = string;
export type Decisions = UpdateDecisionView[];
export type Deployversion1 = number;
export type Deployedcodeversion = number;
export type Authorisedby = string;
export type Candidatehash2 = string;
export type Cause = string;
export type Createdat1 = string;
export type Deployversion2 = number;
export type Faultinjected = string;
export type Finishedat = string | null;
export type Id1 = string;
export type Kind2 = "release" | "rollback";
export type Requestedby = string;
export type Restores = string | null;
export type State =
  | "pending"
  | "running"
  | "succeeded"
  | "compensated"
  | "failed"
  | "awaiting-rollback-approval"
  | "rolled-back"
  | "kept-unverified";
export type Attempt = number;
export type Command1 = string;
export type Error1 = string;
export type Finishedat1 = string | null;
export type Label = string;
export type Logtail1 = string;
export type Movestraffic = boolean;
export type Provider = ("github" | "vercel" | "render" | "neon" | "atlas" | "local-docker") | null;
export type Seq = number;
export type Startedat = string | null;
export type State1 = "pending" | "running" | "succeeded" | "failed" | "compensated" | "skipped";
export type Stepid = string;
export type Steps1 = DeploymentStepView[];
export type Target1 = "local" | "cloud";
export type Url1 = string | null;
export type Verified1 = boolean;
export type Deployments = DeploymentView[];
export type Deploymentstotal = number;
export type Deployversion3 = number | null;
export type Generatedat2 = string;
export type Evidence = string;
export type Evidenceref = string;
export type Id2 = string;
export type Kind3 = "dependency" | "runtime" | "security";
export type Nodeids = string[];
export type Source = "monitoring" | "risk-assessment" | "release";
export type Suggestedrequirement = string;
export type Summary = string;
export type Traces = string[];
export type Items = FeedbackItem[];
export type Projectid1 = string;
export type Reportid = string;
export type Sourcereports = string[];
export type At1 = string;
export type By1 = string;
export type Decision1 = "sent" | "dismissed";
export type Deployversion4 = number;
export type Designversion = number | null;
export type Itemid = string;
export type Note1 = string | null;
export type Feedbackdecisions = FeedbackDecisionView[];
export type At2 = string;
export type By2 = string;
export type Kind4 = "approved" | "changes";
export type Note2 = string | null;
export type Version4 = number;
export type History = GateDecision[];
/**
 * @minItems 1
 */
export type Files = [string, ...string[]];
export type Kind5 = ("actor" | "entity" | "service" | "constraint") | "module";
export type Label1 = string;
/**
 * @minItems 1
 */
export type Links = [ComponentLink, ...ComponentLink[]];
export type Detail3 = string;
export type Path1 = string;
export type Via = "manifest-entity" | "endpoint-entity" | "build-module";
export type Nodeid = string;
export type Traces1 = string[];
/**
 * @minItems 1
 */
export type Updateids = [string, ...string[]];
export type Affectedcomponents = AffectedComponent[];
export type Implements = string[];
export type Manifeststage = string | null;
export type Path2 = string;
export type Referencecount = number;
/**
 * @minItems 1
 */
export type Updateids1 = [string, ...string[]];
export type Affectedfiles = AffectedFile[];
export type Detail4 = string;
export type Kind6 =
  | "removed"
  | "signature-changed"
  | "renamed"
  | "breaking-behaviour"
  | "behaviour-changed"
  | "deprecated"
  | "added"
  | "touched";
export type Source1 = "api-diff" | "changelog";
export type Symbol = string;
export type Tool = string;
export type Updateid4 = string;
export type Changedsymbols = ChangedSymbol[];
export type Codeversion2 = number;
export type Designversion1 = number | null;
export type Extractionid = string;
export type Filesindexed = number;
export type Grammars = string[];
export type Parser = string;
export type Seconds = number;
export type Generatedat3 = string;
export type Granularity = "graph-node" | "module";
export type Apidiff = "ran" | "unavailable" | "failed";
export type Apidiffreason = string;
export type Importspackage = boolean;
export type Match = "import" | "member" | "identifier";
export type Endline = number;
export type Path3 = string;
export type Snippet = string;
export type Startline = number;
export type Symbol1 = string;
export type Symbolkind =
  | "removed"
  | "signature-changed"
  | "renamed"
  | "breaking-behaviour"
  | "behaviour-changed"
  | "deprecated"
  | "added"
  | "touched";
export type References = UsageReference[];
export type Seconds1 = number;
export type Unreferenced = string[];
export type Updateid5 = string;
export type Usedbyscripts = boolean;
export type Perupdate1 = UpdateImpact[];
export type Refusedcount = number;
export type Detail5 = string;
export type Line = number | null;
export type Path4 = string;
export type Reason2 = "file-not-found" | "span-out-of-range" | "snippet-does-not-match";
export type Updateid6 = string;
export type Refusedreferences = RefusedReference[];
export type Detail6 = string;
export type Path5 = string;
export type Reason3 =
  "not-in-manifest" | "implements-nothing-mapped" | "no-graph-node-matches" | "graph-unavailable" | "no-build-module";
export type Unmappedfiles = UnmappedFile[];
export type Version5 = number;
export type Livestate = "healthy" | "degraded" | "down" | "cold-start" | "unknown";
export type Currentstate = "healthy" | "degraded" | "down" | "cold-start" | "unknown";
export type Deploymentid1 = string;
export type At3 = string;
export type Deploymentid2 = string;
export type Detail7 = string;
export type Kind7 =
  | "released"
  | "verified"
  | "degraded"
  | "down"
  | "recovered"
  | "rollback-requested"
  | "rollback-approved"
  | "rolled-back"
  | "rollback-failed";
export type Events = DeploymentEvent[];
export type Expectedcandidatehash = string;
export type Fingerprintmatches = boolean | null;
export type Generatedat4 = string;
export type Idlefrom = ("last-sample" | "released" | "given") | null;
export type Idleseconds = number | null;
export type Probeintervalseconds = number;
export type Lasterror = string;
export type Ok1 = number;
export type P50Ms = number | null;
export type P95Ms = number | null;
export type Probe = string;
export type Samples = number;
export type Probes = ProbeSummary[];
export type Ruleid2 = "health-rule/1";
export type Source2 = string;
export type End = string;
export type Evidence1 = string;
export type Samples1 = number;
export type Start = string;
export type State2 = "healthy" | "degraded" | "down" | "cold-start" | "unknown";
export type States = StateInterval[];
export type Target2 = "local" | "cloud";
export type Coldstartfirstms = number;
export type Coldstartidleseconds = number;
export type Degradedp95Ms = number;
export type Minsamples = number;
/**
 * @minItems 1
 */
export type Urls = [string, ...string[]];
export type Version6 = number;
export type Windowend = string;
export type Windowstart = string;
export type Candidatehash3 = string;
export type Codeversion3 = number;
export type Bytes = number;
export type Path6 = string;
export type Purpose = "workflow" | "container" | "hosting" | "orchestration" | "ignore" | "lockfile" | "fingerprint";
export type Secretsreferenced = string[];
export type Sha256 = string;
export type Templateid = string;
/**
 * Every validator that applies to it ran, and passed.
 */
export type Valid = boolean;
export type Findings = string[];
export type Outcome2 = "passed" | "failed" | "not-run";
export type Reason4 = string;
export type Schemaretrieved = string;
export type Schemaurl = string;
export type Tool1 = string;
export type Validator = "json-schema" | "yaml-parse" | "actionlint" | "hadolint" | "kubeconform" | "secret-scan";
export type Validations = FileValidation[];
export type Files1 = PipelineFile[];
export type Generatedat5 = string;
export type Kubernetes = "generated" | "skipped";
export type Kubernetesreason = string;
export type Backenddir = string | null;
/**
 * @minItems 1
 */
export type Evidence2 = [string, ...string[]];
export type Frontenddir = string | null;
export type Kind8 = "one-process" | "split" | "backend-only" | "frontend-only";
export type Servesfrontendfrombackend = boolean;
export type Shareddirs = string[];
export type Reason5 = string;
export type Stackid = string;
export type Supported = boolean;
/**
 * NFR5: a supported stack whose every generated file is valid.
 */
export type Valid1 = boolean;
export type Version7 = number;
export type Candidatehash4 = string;
export type Deployversion5 = number;
export type Github = "configured" | "unavailable-private-repo" | "unavailable-plan" | "not-applicable";
export type Mechanism = "platform-gate";
export type Reason6 = string;
export type Generatedat6 = string;
export type Generatedby = string;
export type Planid = string;
export type Projectid2 = string;
export type Note3 = string;
export type Strategy = "application-only";
export type Stack = "mern" | "react-spring-postgres";
/**
 * @minItems 1
 */
export type Steps2 = [DeployStep, ...DeployStep[]];
export type Compensation = string | null;
export type Dependson = string | null;
export type Id3 = string;
export type Label2 = string;
export type Movestraffic1 = boolean;
export type Provider1 = ("github" | "vercel" | "render" | "neon" | "atlas" | "local-docker") | null;
export type Target3 = "local" | "cloud";
/**
 * @minItems 1
 */
export type Targets = [DeployTarget, ...DeployTarget[]];
export type Note4 = string | null;
export type Provider2 = "github" | "vercel" | "render" | "neon" | "atlas" | "local-docker";
export type Resource = string;
export type Role = "frontend" | "backend" | "database" | "app";
export type Rootdir = string | null;
export type Runtime = string | null;
export type From = string;
export type Name3 = string;
export type To = string;
export type Wiring = WiringRule[];
export type Projectid3 = string;
export type Releasetarget = "local" | "cloud";
export type Affectedcomponents1 = string[];
export type Affectedfiles1 = string[];
export type Advisory = string;
export type Decidedby = ("semver" | "changelog" | "usage")[];
export type Final = "low" | "medium" | "high";
export type Ruleid3 = "safety-first-max/1";
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
export type Id4 = string;
export type Kind9 = "version" | "claim" | "reference" | "api-diff" | "component";
export type Summary1 = string;
export type Evidence3 = EvidenceRef[];
/**
 * Every vote that was cast cites at least one piece of evidence.
 */
export type Evidencecomplete = boolean;
export type Explanation = string;
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
export type Ruleid4 = "risk-strategy/1";
export type Toversion = string;
export type Updateid7 = string;
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
export type Generatedat7 = string;
export type Latencybudgetseconds = number;
export type Overbudget = number;
export type Arbitration1 = "safety-first-max/1";
export type Changelog = "changelog-rule/1";
export type Semver = "semver-rule/1";
export type Strategy2 = "risk-strategy/1";
export type Usage = "usage-rule/1";
export type Version8 = number;
export type Approval = "required";
/**
 * High updates whose rollback is unavailable, which the release guards refuse.
 */
export type Blocks = string[];
export type Candidatehash5 = string;
export type Expect = string;
export type Id5 = string;
export type Kind10 = "fingerprint" | "health" | "smoke";
export type Role1 = "frontend" | "backend" | "database" | "app";
export type Checks = VerificationCheck[];
export type Datanote = string;
export type Generatedat8 = string;
export type Providerconstraints = string[];
export type Restorable = boolean;
export type Action = string;
export type Constraint = string;
export type Id6 = string;
export type Label3 = string;
export type Movestraffic2 = boolean;
export type Provider3 = "github" | "vercel" | "render" | "neon" | "atlas" | "local-docker";
export type Steps3 = RestoreStep[];
export type Strategy3 = "application-only";
export type Unrestorablereason = string;
export type Level1 = "low" | "medium" | "high";
export type Reason7 = string;
export type Status = "prepared" | "not-required" | "unavailable";
export type Updateid8 = string;
export type Updates = UpdateRollback[];
export type Version9 = number;
/**
 * A release failed after it moved production, and only a human may undo it.
 */
export type Rollbackpending = boolean;
export type Error2 = string | null;
export type Finishedat2 = string | null;
export type Id7 = string;
export type Model = string | null;
export type Startedat1 = string;
export type State3 = "queued" | "running" | "awaiting_gate" | "done" | "failed" | "superseded";
export type Stoppedat = string | null;
export type Thinking1 = string | null;
export type Version10 = number;
export type Scopepackages = string[];
export type Error3 = string | null;
export type Generatedat9 = string | null;
export type Generatedfromversion = number;
export type Id8 =
  | "dependency-updates"
  | "changelog-analysis"
  | "impact-analysis"
  | "risk-assessment"
  | "pipeline-generation"
  | "staging-verification"
  | "rollback-planning"
  | "deployment-review"
  | "release"
  | "monitoring";
/**
 * @minItems 1
 */
export type Answeredby = [string, ...string[]];
export type Reasoningtokens = number;
export type Requests1 = number;
export type Thinking2 = string[];
export type Tokensin = number;
export type Tokensout = number;
export type Status1 = "pending" | "generating" | "complete" | "failed" | "skipped";
export type Summary2 = string | null;
export type Target4 = string;
export type Testversion = number;
export type At4 = string;
export type Author = string;
export type Content = string;
export type Id9 = string;
export type Kind11 = "user_note" | "answer" | "stage_summary" | "system";
export type Producedversion = number | null;
export type Stageid =
  | (
      | "dependency-updates"
      | "changelog-analysis"
      | "impact-analysis"
      | "risk-assessment"
      | "pipeline-generation"
      | "staging-verification"
      | "rollback-planning"
      | "deployment-review"
      | "release"
      | "monitoring"
    )
  | null;
export type Thread = DeployThreadMessage[];
export type Direct = number;
export type Lockfilepath = string;
export type Lockfilesha2562 = string;
export type Packages = number;
export type Resolvedby = string;
export type Codeversion4 = number;
export type Generatedat10 = string;
export type At5 = string;
export type Note5 = string;
export type Registry = string;
export type Status2 = number | null;
export type Url2 = string;
export type Queried = RegistryQuery[];
export type Declared = string;
export type Detail8 = string;
export type Ecosystem1 = "npm" | "maven";
export type Fromversion1 = string | null;
export type Manifestpath = string;
export type Package1 = string;
export type Reason8 =
  | "package-not-found"
  | "version-not-found"
  | "not-a-registry-dependency"
  | "registry-unreachable"
  | "unresolvable-version"
  | "not-an-upgrade"
  | "unsupported-ecosystem";
export type Toversion1 = string | null;
export type Rejected = RejectedUpdate[];
export type Rejectedcount = number;
export type Target5 = string;
export type Testversion1 = number;
export type Uptodate = string[];
export type Alsodeclaredin = string[];
export type Candidate = "in-range" | "latest";
export type Change1 =
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
export type Declared1 = string;
export type Ecosystem2 = "npm" | "maven";
export type Flags = ("initial-development" | "prerelease-target" | "build-metadata" | "qualifier")[];
export type Fromversion2 = string;
export type Id10 = string;
export type Key1 = string;
export type Manifestline = number | null;
export type Manifestpath1 = string;
export type Chars = number;
export type Path7 = string;
export type Sha2561 = string;
export type Source3 = "github-release" | "changelog-file" | "migration-guide";
export type Truncated = boolean;
export type Url3 = string;
export type Version11 = string;
export type Notes = ReleaseNoteRef[];
export type Notesunavailable = string;
export type Package2 = string;
export type Publishedat = string | null;
export type Repositoryurl = string | null;
export type Scope =
  "prod" | "dev" | "peer" | "optional" | "compile" | "test" | "runtime" | "provided" | "plugin" | "import" | "system";
export type Supersededby = string | null;
export type Toversion2 = string;
export type Change2 =
  | (
      | "major"
      | "minor"
      | "patch"
      | "prerelease"
      | "build-only"
      | "beyond-patch"
      | "qualifier"
      | "downgrade"
      | "non-semver"
      | "unparseable"
    )
  | ("added" | "removed");
export type Fromversion3 = string | null;
export type Package3 = string;
export type Toversion3 = string | null;
export type Transitive = TransitiveShift[];
export type Updates1 = DependencyUpdate[];
export type Version12 = number;
export type Watching = string | null;

/**
 * Everything the deployment workspace renders, in one read.
 */
export interface DeploySnapshot {
  analysedTestVersion: Analysedtestversion;
  approvedTestVersion: Approvedtestversion;
  approvedTestedCodeVersion: Approvedtestedcodeversion;
  autoDeployLow: Autodeploylow;
  awaitingDecision: Awaitingdecision;
  blocking: Blocking;
  candidate: ReleaseCandidate | null;
  changelog: ChangelogReport | null;
  cloud: CloudResources | null;
  codeMovedOn: Codemovedon;
  codeVersion: Codeversion1;
  currentRelease: VerifiedRelease | null;
  decisions: Decisions;
  deployVersion: Deployversion1;
  deployedCodeVersion: Deployedcodeversion;
  deployments: Deployments;
  deploymentsTotal: Deploymentstotal;
  feedback: FeedbackReport | null;
  feedbackDecisions: Feedbackdecisions;
  gate: GateState;
  impact: ImpactReport | null;
  liveState: Livestate;
  monitoring: MonitoringReport | null;
  pipeline: PipelineConfig | null;
  plan: DeployPlan | null;
  projectId: Projectid3;
  releaseTarget: Releasetarget;
  risk: RiskReport | null;
  rollback: RollbackPlan | null;
  rollbackPending: Rollbackpending;
  run: RunStatus | null;
  scopePackages: Scopepackages;
  stages: Stages;
  target: Target4;
  testVersion: Testversion;
  thread: Thread;
  updates: DependencyUpdates | null;
  watching: Watching;
}
/**
 * One reason a release may not go ahead, from the server's guards.
 */
export interface Blocker {
  code: Code;
  message: Message;
  updateId: Updateid;
}
/**
 * The `release-candidate` artefact.
 */
export interface ReleaseCandidate {
  candidateHash: Candidatehash;
  codeVersion: Codeversion;
  excluded: Excluded;
  fingerprint: Fingerprint;
  generatedAt: Generatedat;
  image: Image;
  imageDigest: Imagedigest;
  included: Included;
  isolation: Isolation;
  lockfileSha256: Lockfilesha256;
  smoke: Smoke;
  steps: Steps;
  toolchain: Toolchain;
  verified: Verified;
  version: Version;
}
/**
 * An update left out of the candidate, and why.
 */
export interface ExcludedUpdate {
  detail: Detail;
  reason: Reason;
  updateId: Updateid1;
}
/**
 * One request against the booted candidate.
 */
export interface SmokeCheck {
  detail: Detail1;
  method: Method;
  ok: Ok;
  path: Path;
  statusCode: Statuscode;
}
export interface BuildStepReport {
  command: Command;
  durationSeconds: Durationseconds;
  logTail: Logtail;
  name: Name;
  outcome: Outcome;
}
/**
 * The `changelog-report` artefact.
 */
export interface ChangelogReport {
  claimsRefused: Claimsrefused;
  claimsVerified: Claimsverified;
  generatedAt: Generatedat1;
  modelId: Modelid;
  perUpdate: Perupdate;
  promptId: Promptid1;
  promptSha256: Promptsha2561;
  refusalRate: Refusalrate;
  ruleId: Ruleid1;
  stopReason: Stopreason;
  stoppedOnRateLimit: Stoppedonratelimit;
  version: Version3;
}
/**
 * The changelog signal for one update.
 */
export interface ChangelogAnalysis {
  claims: Claims;
  model: ModelCall | null;
  notesFound: Notesfound;
  refused: Refused;
  updateId: Updateid2;
  vote: SignalVote;
  windows: Windows;
}
/**
 * A claim that was checked and holds: the quote is in the notes, in the window.
 */
export interface ChangelogClaim {
  id: Id;
  kind: Kind;
  quote: Quote;
  sourceUrl: Sourceurl;
  symbols: Symbols;
  version: Version1;
}
/**
 * One call to the model, whatever came of it (NFR13).
 */
export interface ModelCall {
  completionTokens: Completiontokens;
  durationSeconds: Durationseconds1;
  error: Error;
  modelId: Modelid1;
  outcome: Outcome1;
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
 * A claim the check refused, kept so the refusal rate is a result.
 */
export interface RefusedClaim {
  detail: Detail2;
  kind: Kind1;
  quote: Quote1;
  reason: Reason1;
  symbols: Symbols1;
  version: Version2;
}
/**
 * One signal's answer for one update, or its reason for having none.
 */
export interface SignalVote {
  abstainedReason: Abstainedreason;
  evidenceIds: Evidenceids;
  level: Level;
  rationale: Rationale;
  ruleId: Ruleid;
  signal: Signal;
}
/**
 * What the platform created for a project's cloud releases.
 *
 * Made on the project's first analysis with the cloud target, from the tokens
 * the account keeps in Settings, and reused after that. Kept per project, so
 * every project releases to its own.
 */
export interface CloudResources {
  createdAt: Createdat;
  database: AtlasDatabase | null;
  render: RenderService;
  vercel: VercelProject;
}
/**
 * The project's own database on the account's Atlas cluster, and who may use it.
 *
 * The password is not here: the platform keeps it encrypted with its secrets,
 * and it reaches only Atlas and the Render service, inside MONGODB_URL.
 */
export interface AtlasDatabase {
  cluster: Cluster;
  database: Database;
  host: Host;
  serviceId: Serviceid;
  username: Username;
}
/**
 * The Render web service the platform created for a project's backend.
 */
export interface RenderService {
  dashboardUrl: Dashboardurl;
  name: Name1;
  origin: Origin;
  ownerId: Ownerid;
  serviceId: Serviceid1;
}
/**
 * The Vercel project the platform created for a project's frontend.
 */
export interface VercelProject {
  name: Name2;
  orgId: Orgid;
  origin: Origin1;
  projectId: Projectid;
}
/**
 * A release that passed verification where it runs, which a restore can return to.
 */
export interface VerifiedRelease {
  candidateHash: Candidatehash1;
  commitSha: Commitsha;
  deployVersion: Deployversion;
  deploymentId: Deploymentid;
  imageDigest: Imagedigest1;
  lockfileSha256: Lockfilesha2561;
  renderDeployId: Renderdeployid;
  target: Target;
  url: Url;
  vercelDeploymentId: Verceldeploymentid;
  verifiedAt: Verifiedat;
}
/**
 * What a person decided about one update, and whether a decision is owed.
 */
export interface UpdateDecisionView {
  at: At;
  by: By;
  decision: Decision;
  levelAtDecision: Levelatdecision;
  needsDecision: Needsdecision;
  needsReviewNote: Needsreviewnote;
  note: Note;
  updateId: Updateid3;
}
/**
 * One attempt to release or roll back, whatever came of it (FR16).
 */
export interface DeploymentView {
  authorisedBy: Authorisedby;
  candidateHash: Candidatehash2;
  cause: Cause;
  createdAt: Createdat1;
  deployVersion: Deployversion2;
  faultInjected: Faultinjected;
  finishedAt: Finishedat;
  id: Id1;
  kind: Kind2;
  requestedBy: Requestedby;
  restores: Restores;
  state: State;
  steps: Steps1;
  target: Target1;
  url: Url1;
  verified: Verified1;
}
/**
 * One step of one deployment, in the shape the shared console reads.
 */
export interface DeploymentStepView {
  attempt: Attempt;
  command: Command1;
  error: Error1;
  finishedAt: Finishedat1;
  label: Label;
  logTail: Logtail1;
  movesTraffic: Movestraffic;
  provider: Provider;
  seq: Seq;
  startedAt: Startedat;
  state: State1;
  stepId: Stepid;
}
export interface FeedbackReport {
  deployVersion: Deployversion3;
  generatedAt: Generatedat2;
  items: Items;
  projectId: Projectid1;
  reportId: Reportid;
  sourceReports: Sourcereports;
}
export interface FeedbackItem {
  evidence: Evidence;
  evidenceRef: Evidenceref;
  id: Id2;
  kind: Kind3;
  nodeIds: Nodeids;
  source: Source;
  suggestedRequirement: Suggestedrequirement;
  summary: Summary;
  traces: Traces;
}
/**
 * What a person did with one feedback item (M5).
 */
export interface FeedbackDecisionView {
  at: At1;
  by: By1;
  decision: Decision1;
  deployVersion: Deployversion4;
  designVersion: Designversion;
  itemId: Itemid;
  note: Note1;
}
export interface GateState {
  decision: GateDecision | null;
  history: History;
}
export interface GateDecision {
  at: At2;
  by: By2;
  kind: Kind4;
  note: Note2;
  version: Version4;
}
/**
 * The `impact-report` artefact.
 */
export interface ImpactReport {
  affectedComponents: Affectedcomponents;
  affectedFiles: Affectedfiles;
  changedSymbols: Changedsymbols;
  codeVersion: Codeversion2;
  designVersion: Designversion1;
  extraction: ExtractionRecord;
  generatedAt: Generatedat3;
  granularity: Granularity;
  perUpdate: Perupdate1;
  refusedCount: Refusedcount;
  refusedReferences: Refusedreferences;
  unmappedFiles: Unmappedfiles;
  version: Version5;
}
/**
 * An architectural component an update reaches, and how that is known.
 */
export interface AffectedComponent {
  files: Files;
  kind: Kind5;
  label: Label1;
  links: Links;
  nodeId: Nodeid;
  traces: Traces1;
  updateIds: Updateids;
}
/**
 * One recorded reason a file belongs to a component.
 */
export interface ComponentLink {
  detail: Detail3;
  path: Path1;
  via: Via;
}
/**
 * A file that uses something an update changed.
 */
export interface AffectedFile {
  implements: Implements;
  manifestStage: Manifeststage;
  path: Path2;
  referenceCount: Referencecount;
  updateIds: Updateids1;
}
/**
 * One symbol an update changes, and who said so.
 */
export interface ChangedSymbol {
  detail: Detail4;
  kind: Kind6;
  source: Source1;
  symbol: Symbol;
  tool: Tool;
  updateId: Updateid4;
}
/**
 * The one index this run built, so a reader can see it was built once.
 */
export interface ExtractionRecord {
  extractionId: Extractionid;
  filesIndexed: Filesindexed;
  grammars: Grammars;
  parser: Parser;
  seconds: Seconds;
}
/**
 * Signal three for one update.
 */
export interface UpdateImpact {
  apiDiff: Apidiff;
  apiDiffReason: Apidiffreason;
  importsPackage: Importspackage;
  references: References;
  seconds: Seconds1;
  unreferenced: Unreferenced;
  updateId: Updateid5;
  usedByScripts: Usedbyscripts;
  vote: SignalVote;
}
/**
 * One place the project uses a changed symbol, checked against the file.
 */
export interface UsageReference {
  match: Match;
  span: EvidenceSpan;
  symbol: Symbol1;
  symbolKind: Symbolkind;
}
/**
 * Where in the repository the finding is, precisely enough to check.
 *
 * A span rather than a line, because a taint finding is a flow and a reader
 * asked to confirm one line of it is being asked to trust the rest.
 */
export interface EvidenceSpan {
  endLine: Endline;
  path: Path3;
  snippet: Snippet;
  startLine: Startline;
}
/**
 * A reference that did not survive being re-read.
 */
export interface RefusedReference {
  detail: Detail5;
  line: Line;
  path: Path4;
  reason: Reason2;
  updateId: Updateid6;
}
/**
 * An affected file no component could honestly be named for.
 */
export interface UnmappedFile {
  detail: Detail6;
  path: Path5;
  reason: Reason3;
}
/**
 * The `monitoring-report` artefact.
 */
export interface MonitoringReport {
  currentState: Currentstate;
  deploymentId: Deploymentid1;
  events: Events;
  expectedCandidateHash: Expectedcandidatehash;
  fingerprintMatches: Fingerprintmatches;
  generatedAt: Generatedat4;
  idleFrom: Idlefrom;
  idleSeconds: Idleseconds;
  probeIntervalSeconds: Probeintervalseconds;
  probes: Probes;
  ruleId: Ruleid2;
  source: Source2;
  states: States;
  target: Target2;
  thresholds: HealthThresholds;
  urls: Urls;
  version: Version6;
  windowEnd: Windowend;
  windowStart: Windowstart;
}
export interface DeploymentEvent {
  at: At3;
  deploymentId: Deploymentid2;
  detail: Detail7;
  kind: Kind7;
}
/**
 * One kind of probe across the window.
 */
export interface ProbeSummary {
  lastError: Lasterror;
  ok: Ok1;
  p50Ms: P50Ms;
  p95Ms: P95Ms;
  probe: Probe;
  samples: Samples;
}
/**
 * One stretch of the window in one state, and what put it there.
 */
export interface StateInterval {
  end: End;
  evidence: Evidence1;
  samples: Samples1;
  start: Start;
  state: State2;
}
/**
 * The numbers the health rule compares against, recorded with its verdict.
 */
export interface HealthThresholds {
  coldStartFirstMs: Coldstartfirstms;
  coldStartIdleSeconds: Coldstartidleseconds;
  degradedP95Ms: Degradedp95Ms;
  minSamples: Minsamples;
}
/**
 * The `pipeline-config` artefact.
 */
export interface PipelineConfig {
  candidateHash: Candidatehash3;
  codeVersion: Codeversion3;
  files: Files1;
  generatedAt: Generatedat5;
  kubernetes: Kubernetes;
  kubernetesReason: Kubernetesreason;
  stack: StackSupport;
  valid: Valid1;
  version: Version7;
}
/**
 * One generated file.
 */
export interface PipelineFile {
  bytes: Bytes;
  path: Path6;
  purpose: Purpose;
  secretsReferenced: Secretsreferenced;
  sha256: Sha256;
  templateId: Templateid;
  valid: Valid;
  validations: Validations;
}
/**
 * One validator's verdict on one file.
 */
export interface FileValidation {
  findings: Findings;
  outcome: Outcome2;
  reason: Reason4;
  schemaRetrieved: Schemaretrieved;
  schemaUrl: Schemaurl;
  tool: Tool1;
  validator: Validator;
}
/**
 * Whether this stack has validated templates, and if not, why (FR14).
 */
export interface StackSupport {
  layout: ArchitecturalLayout | null;
  reason: Reason5;
  stackId: Stackid;
  supported: Supported;
}
/**
 * How the project is laid out, and the facts that decided it.
 */
export interface ArchitecturalLayout {
  backendDir: Backenddir;
  evidence: Evidence2;
  frontendDir: Frontenddir;
  kind: Kind8;
  servesFrontendFromBackend: Servesfrontendfrombackend;
  sharedDirs: Shareddirs;
}
export interface DeployPlan {
  candidateHash: Candidatehash4;
  deployVersion: Deployversion5;
  environmentProtection: EnvironmentProtection;
  generatedAt: Generatedat6;
  generatedBy: Generatedby;
  planId: Planid;
  projectId: Projectid2;
  rollback: RollbackPolicy;
  stack: Stack;
  steps: Steps2;
  target: Target3;
  targets: Targets;
  wiring: Wiring;
}
/**
 * Which approval locks were in force for this plan.
 */
export interface EnvironmentProtection {
  github: Github;
  mechanism: Mechanism;
  reason: Reason6;
}
export interface RollbackPolicy {
  note: Note3;
  strategy: Strategy;
}
export interface DeployStep {
  compensation: Compensation;
  dependsOn: Dependson;
  id: Id3;
  label: Label2;
  movesTraffic: Movestraffic1;
  provider: Provider1;
}
export interface DeployTarget {
  note: Note4;
  provider: Provider2;
  resource: Resource;
  role: Role;
  rootDir: Rootdir;
  runtime: Runtime;
}
/**
 * How one part learns the address of another, in plain words.
 */
export interface WiringRule {
  from: From;
  name: Name3;
  to: To;
}
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
  generatedAt: Generatedat7;
  latencyBudgetSeconds: Latencybudgetseconds;
  overBudget: Overbudget;
  rules: RuleSet;
  version: Version8;
}
/**
 * One update, assessed.
 */
export interface UpdateAssessment {
  affectedComponents: Affectedcomponents1;
  affectedFiles: Affectedfiles1;
  arbitration: Arbitration;
  change: Change;
  disagreement: Disagreement;
  ecosystem: Ecosystem;
  evidence: Evidence3;
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
  strategy: Strategy1;
  toVersion: Toversion;
  updateId: Updateid7;
  votes: Votes;
}
/**
 * How the votes became one level (FR6, FR7).
 */
export interface Arbitration {
  advisory: Advisory;
  decidedBy: Decidedby;
  final: Final;
  ruleId: Ruleid3;
}
/**
 * One piece of evidence a vote rests on, summarised for a reader.
 */
export interface EvidenceRef {
  id: Id4;
  kind: Kind9;
  summary: Summary1;
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
export interface Strategy1 {
  deploy: Deploy;
  manualReviewRequired: Manualreviewrequired;
  rollbackRequired: Rollbackrequired;
  ruleId: Ruleid4;
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
  strategy: Strategy2;
  usage: Usage;
}
/**
 * The `rollback-plan` artefact.
 */
export interface RollbackPlan {
  approval: Approval;
  blocks: Blocks;
  candidateHash: Candidatehash5;
  checks: Checks;
  dataNote: Datanote;
  generatedAt: Generatedat8;
  providerConstraints: Providerconstraints;
  restorable: Restorable;
  restoreTarget: VerifiedRelease | null;
  steps: Steps3;
  strategy: Strategy3;
  unrestorableReason: Unrestorablereason;
  updates: Updates;
  version: Version9;
}
export interface VerificationCheck {
  expect: Expect;
  id: Id5;
  kind: Kind10;
  role: Role1;
}
export interface RestoreStep {
  action: Action;
  constraint: Constraint;
  id: Id6;
  label: Label3;
  movesTraffic: Movestraffic2;
  provider: Provider3;
}
/**
 * Whether a rollback is prepared for one update, as FR17 and FR19 require.
 */
export interface UpdateRollback {
  level: Level1;
  reason: Reason7;
  status: Status;
  updateId: Updateid8;
}
/**
 * The phase's newest full run.
 *
 * A stage retry is a run of its own, and it is not this one: it reports on
 * its own stage, and a retry that finished must not hide the full run beneath
 * it that stopped short of the review.
 */
export interface RunStatus {
  error: Error2;
  finishedAt: Finishedat2;
  id: Id7;
  model: Model;
  startedAt: Startedat1;
  state: State3;
  stoppedAt: Stoppedat;
  thinking: Thinking1;
  version: Version10;
}
export interface Stages {
  [k: string]: DeployStageState;
}
/**
 * One stage of the deployment phase, as the stepper renders it.
 */
export interface DeployStageState {
  error: Error3;
  generatedAt: Generatedat9;
  generatedFromVersion: Generatedfromversion;
  id: Id8;
  modelUse: StageModelUse | null;
  status: Status1;
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
  requests: Requests1;
  thinking: Thinking2;
  tokensIn: Tokensin;
  tokensOut: Tokensout;
}
export interface DeployThreadMessage {
  at: At4;
  author: Author;
  content: Content;
  id: Id9;
  kind: Kind11;
  producedVersion: Producedversion;
  stageId: Stageid;
}
/**
 * The `dependency-updates` artefact: one deploy version's view of the registries.
 */
export interface DependencyUpdates {
  baseline: BaselinePin | null;
  codeVersion: Codeversion4;
  generatedAt: Generatedat10;
  queried: Queried;
  rejected: Rejected;
  rejectedCount: Rejectedcount;
  target: Target5;
  testVersion: Testversion1;
  upToDate: Uptodate;
  updates: Updates1;
  version: Version12;
}
/**
 * The exact dependency set the analysis starts from.
 *
 * The generated projects carry no lockfile and caret ranges throughout, so
 * until this was recorded nothing said which versions the tested build had
 * installed. A rollback that restores "the previous release" restores this.
 */
export interface BaselinePin {
  direct: Direct;
  lockfilePath: Lockfilepath;
  lockfileSha256: Lockfilesha2562;
  packages: Packages;
  resolvedBy: Resolvedby;
}
/**
 * One question asked of a registry, and whether it answered.
 *
 * Recorded so that "no newer version" can be told apart from "the registry
 * was not reachable", which read the same in a list of updates.
 */
export interface RegistryQuery {
  at: At5;
  note: Note5;
  registry: Registry;
  status: Status2;
  url: Url2;
}
/**
 * An update that could not be analysed, and why (FR3).
 */
export interface RejectedUpdate {
  declared: Declared;
  detail: Detail8;
  ecosystem: Ecosystem1;
  fromVersion: Fromversion1;
  manifestPath: Manifestpath;
  package: Package1;
  reason: Reason8;
  toVersion: Toversion1;
}
/**
 * One update the registry offers, and everything retrieved about it.
 */
export interface DependencyUpdate {
  alsoDeclaredIn: Alsodeclaredin;
  candidate: Candidate;
  change: Change1;
  declared: Declared1;
  ecosystem: Ecosystem2;
  flags: Flags;
  fromVersion: Fromversion2;
  id: Id10;
  key: Key1;
  manifestLine: Manifestline;
  manifestPath: Manifestpath1;
  notes: Notes;
  notesUnavailable: Notesunavailable;
  package: Package2;
  publishedAt: Publishedat;
  repositoryUrl: Repositoryurl;
  scope: Scope;
  supersededBy: Supersededby;
  toVersion: Toversion2;
  transitive: Transitive;
}
/**
 * One release note text, as read, with where the stored copy lives.
 */
export interface ReleaseNoteRef {
  chars: Chars;
  path: Path7;
  sha256: Sha2561;
  source: Source3;
  truncated: Truncated;
  url: Url3;
  version: Version11;
}
/**
 * A package the update moves without being asked to, seen in the lockfile.
 *
 * `added` and `removed` are a package appearing in or leaving the tree, which
 * is not a move between two versions and is not given a SemVer name.
 */
export interface TransitiveShift {
  change: Change2;
  fromVersion: Fromversion3;
  package: Package3;
  toVersion: Toversion3;
}

/**
 * Generated from contracts/*.schema.json. Do not edit by hand.
 *
 * Regenerate with: npm run gen:contracts
 * The schemas themselves are generated from the Pydantic models in
 * packages/contracts-py, which are the single author of every artefact shape.
 */

export type Currentstate = "healthy" | "degraded" | "down" | "cold-start" | "unknown";
export type Deploymentid = string;
export type At = string;
export type Deploymentid1 = string;
export type Detail = string;
export type Kind =
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
export type Generatedat = string;
export type Idlefrom = ("last-sample" | "released" | "given") | null;
export type Idleseconds = number | null;
export type Probeintervalseconds = number;
export type Lasterror = string;
export type Ok = number;
export type P50Ms = number | null;
export type P95Ms = number | null;
export type Probe = string;
export type Samples = number;
export type Probes = ProbeSummary[];
export type Ruleid = "health-rule/1";
export type Source = string;
export type End = string;
export type Evidence = string;
export type Samples1 = number;
export type Start = string;
export type State = "healthy" | "degraded" | "down" | "cold-start" | "unknown";
export type States = StateInterval[];
export type Target = "local" | "cloud";
export type Coldstartfirstms = number;
export type Coldstartidleseconds = number;
export type Degradedp95Ms = number;
export type Minsamples = number;
/**
 * @minItems 1
 */
export type Urls = [string, ...string[]];
export type Version = number;
export type Windowend = string;
export type Windowstart = string;

/**
 * The `monitoring-report` artefact.
 */
export interface MonitoringReport {
  currentState: Currentstate;
  deploymentId: Deploymentid;
  events: Events;
  expectedCandidateHash: Expectedcandidatehash;
  fingerprintMatches: Fingerprintmatches;
  generatedAt: Generatedat;
  idleFrom: Idlefrom;
  idleSeconds: Idleseconds;
  probeIntervalSeconds: Probeintervalseconds;
  probes: Probes;
  ruleId: Ruleid;
  source: Source;
  states: States;
  target: Target;
  thresholds: HealthThresholds;
  urls: Urls;
  version: Version;
  windowEnd: Windowend;
  windowStart: Windowstart;
}
export interface DeploymentEvent {
  at: At;
  deploymentId: Deploymentid1;
  detail: Detail;
  kind: Kind;
}
/**
 * One kind of probe across the window.
 */
export interface ProbeSummary {
  lastError: Lasterror;
  ok: Ok;
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
  evidence: Evidence;
  samples: Samples1;
  start: Start;
  state: State;
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

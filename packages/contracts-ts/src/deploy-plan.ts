/**
 * Generated from contracts/*.schema.json. Do not edit by hand.
 *
 * Regenerate with: npm run gen:contracts
 * The schemas themselves are generated from the Pydantic models in
 * packages/contracts-py, which are the single author of every artefact shape.
 */

export type Candidatehash = string;
export type Deployversion = number;
export type Github = "configured" | "unavailable-private-repo" | "unavailable-plan" | "not-applicable";
export type Mechanism = "platform-gate";
export type Reason = string;
export type Generatedat = string;
export type Generatedby = string;
export type Planid = string;
export type Projectid = string;
export type Note = string;
export type Strategy = "application-only";
export type Stack = "mern" | "react-spring-postgres";
/**
 * @minItems 1
 */
export type Steps = [DeployStep, ...DeployStep[]];
export type Compensation = string | null;
export type Dependson = string | null;
export type Id = string;
export type Label = string;
export type Movestraffic = boolean;
export type Provider = ("github" | "vercel" | "render" | "neon" | "atlas" | "local-docker") | null;
export type Target = "local" | "cloud";
/**
 * @minItems 1
 */
export type Targets = [DeployTarget, ...DeployTarget[]];
export type Note1 = string | null;
export type Provider1 = "github" | "vercel" | "render" | "neon" | "atlas" | "local-docker";
export type Resource = string;
export type Role = "frontend" | "backend" | "database" | "app";
export type Rootdir = string | null;
export type Runtime = string | null;
export type From = string;
export type Name = string;
export type To = string;
export type Wiring = WiringRule[];

export interface DeployPlan {
  candidateHash: Candidatehash;
  deployVersion: Deployversion;
  environmentProtection: EnvironmentProtection;
  generatedAt: Generatedat;
  generatedBy: Generatedby;
  planId: Planid;
  projectId: Projectid;
  rollback: RollbackPolicy;
  stack: Stack;
  steps: Steps;
  target: Target;
  targets: Targets;
  wiring: Wiring;
}
/**
 * Which approval locks were in force for this plan.
 */
export interface EnvironmentProtection {
  github: Github;
  mechanism: Mechanism;
  reason: Reason;
}
export interface RollbackPolicy {
  note: Note;
  strategy: Strategy;
}
export interface DeployStep {
  compensation: Compensation;
  dependsOn: Dependson;
  id: Id;
  label: Label;
  movesTraffic: Movestraffic;
  provider: Provider;
}
export interface DeployTarget {
  note: Note1;
  provider: Provider1;
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
  name: Name;
  to: To;
}

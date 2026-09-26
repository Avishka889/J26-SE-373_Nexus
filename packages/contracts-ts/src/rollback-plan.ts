/**
 * Generated from contracts/*.schema.json. Do not edit by hand.
 *
 * Regenerate with: npm run gen:contracts
 * The schemas themselves are generated from the Pydantic models in
 * packages/contracts-py, which are the single author of every artefact shape.
 */

export type Approval = "required";
/**
 * High updates whose rollback is unavailable, which the release guards refuse.
 */
export type Blocks = string[];
export type Candidatehash = string;
export type Expect = string;
export type Id = string;
export type Kind = "fingerprint" | "health" | "smoke";
export type Role = "frontend" | "backend" | "database" | "app";
export type Checks = VerificationCheck[];
export type Datanote = string;
export type Generatedat = string;
export type Providerconstraints = string[];
export type Restorable = boolean;
export type Candidatehash1 = string;
export type Commitsha = string | null;
export type Deployversion = number;
export type Deploymentid = string;
export type Imagedigest = string | null;
export type Lockfilesha256 = string | null;
export type Renderdeployid = string | null;
export type Target = "local" | "cloud";
export type Url = string | null;
export type Verceldeploymentid = string | null;
export type Verifiedat = string;
export type Action = string;
export type Constraint = string;
export type Id1 = string;
export type Label = string;
export type Movestraffic = boolean;
export type Provider = "github" | "vercel" | "render" | "neon" | "atlas" | "local-docker";
export type Steps = RestoreStep[];
export type Strategy = "application-only";
export type Unrestorablereason = string;
export type Level = "low" | "medium" | "high";
export type Reason = string;
export type Status = "prepared" | "not-required" | "unavailable";
export type Updateid = string;
export type Updates = UpdateRollback[];
export type Version = number;

/**
 * The `rollback-plan` artefact.
 */
export interface RollbackPlan {
  approval: Approval;
  blocks: Blocks;
  candidateHash: Candidatehash;
  checks: Checks;
  dataNote: Datanote;
  generatedAt: Generatedat;
  providerConstraints: Providerconstraints;
  restorable: Restorable;
  restoreTarget: VerifiedRelease | null;
  steps: Steps;
  strategy: Strategy;
  unrestorableReason: Unrestorablereason;
  updates: Updates;
  version: Version;
}
export interface VerificationCheck {
  expect: Expect;
  id: Id;
  kind: Kind;
  role: Role;
}
/**
 * A release that passed verification where it runs, which a restore can return to.
 */
export interface VerifiedRelease {
  candidateHash: Candidatehash1;
  commitSha: Commitsha;
  deployVersion: Deployversion;
  deploymentId: Deploymentid;
  imageDigest: Imagedigest;
  lockfileSha256: Lockfilesha256;
  renderDeployId: Renderdeployid;
  target: Target;
  url: Url;
  vercelDeploymentId: Verceldeploymentid;
  verifiedAt: Verifiedat;
}
export interface RestoreStep {
  action: Action;
  constraint: Constraint;
  id: Id1;
  label: Label;
  movesTraffic: Movestraffic;
  provider: Provider;
}
/**
 * Whether a rollback is prepared for one update, as FR17 and FR19 require.
 */
export interface UpdateRollback {
  level: Level;
  reason: Reason;
  status: Status;
  updateId: Updateid;
}

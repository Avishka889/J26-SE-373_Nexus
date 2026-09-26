/**
 * Generated from contracts/*.schema.json. Do not edit by hand.
 *
 * Regenerate with: npm run gen:contracts
 * The schemas themselves are generated from the Pydantic models in
 * packages/contracts-py, which are the single author of every artefact shape.
 */

export type Candidatehash = string;
export type Codeversion = number;
export type Detail = string;
export type Reason = "rejected" | "deferred" | "no-restore-target" | "superseded" | "out-of-scope";
export type Updateid = string;
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
  updateId: Updateid;
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

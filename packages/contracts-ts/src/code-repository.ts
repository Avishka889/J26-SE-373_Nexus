/**
 * Generated from contracts/*.schema.json. Do not edit by hand.
 *
 * Regenerate with: npm run gen:contracts
 * The schemas themselves are generated from the Pydantic models in
 * packages/contracts-py, which are the single author of every artefact shape.
 */

export type Isolation = string;
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
export type Arm = "rule" | "llm" | "merged";
export type Carriedfixes = number[];
export type Generator = "static" | "rule" | "model";
export type Implements = string[];
export type Path = string;
export type Reusedfromversion = number;
export type Stage = string;
export type Summary = string;
export type Writtenfrom = string;
export type Manifest = ManifestRow[];
export type Notpushedreason = string | null;
export type Branch = string;
export type Commitsha = string;
export type Defaultbranch = string;
export type Name1 = string;
export type Owner = string;
export type Provider = "github";
export type Pullrequestnumber = number | null;
export type Pullrequesturl = string;
export type Url = string;
export type Version = number;

export interface CodeRepository {
  build: BuildReport | null;
  manifest: Manifest;
  notPushedReason: Notpushedreason;
  repository: RepositoryPointer | null;
  version: Version;
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
  name: Name;
  outcome: Outcome;
}
export interface ManifestRow {
  arm: Arm;
  carriedFixes: Carriedfixes;
  generator: Generator;
  implements: Implements;
  path: Path;
  reusedFromVersion: Reusedfromversion;
  stage: Stage;
  summary: Summary;
  writtenFrom: Writtenfrom;
}
export interface RepositoryPointer {
  branch: Branch;
  commitSha: Commitsha;
  defaultBranch: Defaultbranch;
  name: Name1;
  owner: Owner;
  provider: Provider;
  pullRequestNumber: Pullrequestnumber;
  pullRequestUrl: Pullrequesturl;
  url: Url;
}

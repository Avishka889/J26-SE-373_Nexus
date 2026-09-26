/**
 * Generated from contracts/*.schema.json. Do not edit by hand.
 *
 * Regenerate with: npm run gen:contracts
 * The schemas themselves are generated from the Pydantic models in
 * packages/contracts-py, which are the single author of every artefact shape.
 */

export type Direct = number;
export type Lockfilepath = string;
export type Lockfilesha256 = string;
export type Packages = number;
export type Resolvedby = string;
export type Codeversion = number;
export type Generatedat = string;
export type At = string;
export type Note = string;
export type Registry = string;
export type Status = number | null;
export type Url = string;
export type Queried = RegistryQuery[];
export type Declared = string;
export type Detail = string;
export type Ecosystem = "npm" | "maven";
export type Fromversion = string | null;
export type Manifestpath = string;
export type Package = string;
export type Reason =
  | "package-not-found"
  | "version-not-found"
  | "not-a-registry-dependency"
  | "registry-unreachable"
  | "unresolvable-version"
  | "not-an-upgrade"
  | "unsupported-ecosystem";
export type Toversion = string | null;
export type Rejected = RejectedUpdate[];
export type Rejectedcount = number;
export type Target = string;
export type Testversion = number;
export type Uptodate = string[];
export type Alsodeclaredin = string[];
export type Candidate = "in-range" | "latest";
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
export type Declared1 = string;
export type Ecosystem1 = "npm" | "maven";
export type Flags = ("initial-development" | "prerelease-target" | "build-metadata" | "qualifier")[];
export type Fromversion1 = string;
export type Id = string;
export type Key = string;
export type Manifestline = number | null;
export type Manifestpath1 = string;
export type Chars = number;
export type Path = string;
export type Sha256 = string;
export type Source = "github-release" | "changelog-file" | "migration-guide";
export type Truncated = boolean;
export type Url1 = string;
export type Version = string;
export type Notes = ReleaseNoteRef[];
export type Notesunavailable = string;
export type Package1 = string;
export type Publishedat = string | null;
export type Repositoryurl = string | null;
export type Scope =
  "prod" | "dev" | "peer" | "optional" | "compile" | "test" | "runtime" | "provided" | "plugin" | "import" | "system";
export type Supersededby = string | null;
export type Toversion1 = string;
export type Change1 =
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
export type Fromversion2 = string | null;
export type Package2 = string;
export type Toversion2 = string | null;
export type Transitive = TransitiveShift[];
export type Updates = DependencyUpdate[];
export type Version1 = number;

/**
 * The `dependency-updates` artefact: one deploy version's view of the registries.
 */
export interface DependencyUpdates {
  baseline: BaselinePin | null;
  codeVersion: Codeversion;
  generatedAt: Generatedat;
  queried: Queried;
  rejected: Rejected;
  rejectedCount: Rejectedcount;
  target: Target;
  testVersion: Testversion;
  upToDate: Uptodate;
  updates: Updates;
  version: Version1;
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
  lockfileSha256: Lockfilesha256;
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
  at: At;
  note: Note;
  registry: Registry;
  status: Status;
  url: Url;
}
/**
 * An update that could not be analysed, and why (FR3).
 */
export interface RejectedUpdate {
  declared: Declared;
  detail: Detail;
  ecosystem: Ecosystem;
  fromVersion: Fromversion;
  manifestPath: Manifestpath;
  package: Package;
  reason: Reason;
  toVersion: Toversion;
}
/**
 * One update the registry offers, and everything retrieved about it.
 */
export interface DependencyUpdate {
  alsoDeclaredIn: Alsodeclaredin;
  candidate: Candidate;
  change: Change;
  declared: Declared1;
  ecosystem: Ecosystem1;
  flags: Flags;
  fromVersion: Fromversion1;
  id: Id;
  key: Key;
  manifestLine: Manifestline;
  manifestPath: Manifestpath1;
  notes: Notes;
  notesUnavailable: Notesunavailable;
  package: Package1;
  publishedAt: Publishedat;
  repositoryUrl: Repositoryurl;
  scope: Scope;
  supersededBy: Supersededby;
  toVersion: Toversion1;
  transitive: Transitive;
}
/**
 * One release note text, as read, with where the stored copy lives.
 */
export interface ReleaseNoteRef {
  chars: Chars;
  path: Path;
  sha256: Sha256;
  source: Source;
  truncated: Truncated;
  url: Url1;
  version: Version;
}
/**
 * A package the update moves without being asked to, seen in the lockfile.
 *
 * `added` and `removed` are a package appearing in or leaving the tree, which
 * is not a move between two versions and is not given a SemVer name.
 */
export interface TransitiveShift {
  change: Change1;
  fromVersion: Fromversion2;
  package: Package2;
  toVersion: Toversion2;
}

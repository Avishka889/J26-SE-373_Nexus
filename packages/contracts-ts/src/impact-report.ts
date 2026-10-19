/**
 * Generated from contracts/*.schema.json. Do not edit by hand.
 *
 * Regenerate with: npm run gen:contracts
 * The schemas themselves are generated from the Pydantic models in
 * packages/contracts-py, which are the single author of every artefact shape.
 */

/**
 * @minItems 1
 */
export type Files = [string, ...string[]];
export type Kind = ("actor" | "entity" | "service" | "constraint") | "module";
export type Label = string;
/**
 * @minItems 1
 */
export type Links = [ComponentLink, ...ComponentLink[]];
export type Detail = string;
export type Path = string;
export type Via = "manifest-entity" | "endpoint-entity" | "build-module";
export type Nodeid = string;
export type Traces = string[];
/**
 * @minItems 1
 */
export type Updateids = [string, ...string[]];
export type Affectedcomponents = AffectedComponent[];
export type Implements = string[];
export type Manifeststage = string | null;
export type Path1 = string;
export type Referencecount = number;
/**
 * @minItems 1
 */
export type Updateids1 = [string, ...string[]];
export type Affectedfiles = AffectedFile[];
export type Detail1 = string;
export type Kind1 =
  | "removed"
  | "signature-changed"
  | "renamed"
  | "breaking-behaviour"
  | "behaviour-changed"
  | "deprecated"
  | "added"
  | "touched";
export type Source = "api-diff" | "changelog";
export type Symbol = string;
export type Tool = string;
export type Updateid = string;
export type Changedsymbols = ChangedSymbol[];
export type Codeversion = number;
export type Designversion = number | null;
export type Extractionid = string;
export type Filesindexed = number;
export type Grammars = string[];
export type Parser = string;
export type Seconds = number;
export type Generatedat = string;
export type Granularity = "graph-node" | "module";
export type Apidiff = "ran" | "unavailable" | "failed";
export type Apidiffreason = string;
export type Importspackage = boolean;
export type Match = "import" | "member" | "identifier";
export type Endline = number;
export type Path2 = string;
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
export type Updateid1 = string;
export type Usedbyscripts = boolean;
export type Abstainedreason = string;
export type Evidenceids = string[];
export type Level = ("low" | "medium" | "high") | null;
export type Rationale = string;
export type Ruleid = string;
export type Signal = "semver" | "changelog" | "usage";
export type Perupdate = UpdateImpact[];
export type Refusedcount = number;
export type Detail2 = string;
export type Line = number | null;
export type Path3 = string;
export type Reason = "file-not-found" | "span-out-of-range" | "snippet-does-not-match";
export type Updateid2 = string;
export type Refusedreferences = RefusedReference[];
export type Detail3 = string;
export type Path4 = string;
export type Reason1 =
  "not-in-manifest" | "implements-nothing-mapped" | "no-graph-node-matches" | "graph-unavailable" | "no-build-module";
export type Unmappedfiles = UnmappedFile[];
export type Version = number;

/**
 * The `impact-report` artefact.
 */
export interface ImpactReport {
  affectedComponents: Affectedcomponents;
  affectedFiles: Affectedfiles;
  changedSymbols: Changedsymbols;
  codeVersion: Codeversion;
  designVersion: Designversion;
  extraction: ExtractionRecord;
  generatedAt: Generatedat;
  granularity: Granularity;
  perUpdate: Perupdate;
  refusedCount: Refusedcount;
  refusedReferences: Refusedreferences;
  unmappedFiles: Unmappedfiles;
  version: Version;
}
/**
 * An architectural component an update reaches, and how that is known.
 */
export interface AffectedComponent {
  files: Files;
  kind: Kind;
  label: Label;
  links: Links;
  nodeId: Nodeid;
  traces: Traces;
  updateIds: Updateids;
}
/**
 * One recorded reason a file belongs to a component.
 */
export interface ComponentLink {
  detail: Detail;
  path: Path;
  via: Via;
}
/**
 * A file that uses something an update changed.
 */
export interface AffectedFile {
  implements: Implements;
  manifestStage: Manifeststage;
  path: Path1;
  referenceCount: Referencecount;
  updateIds: Updateids1;
}
/**
 * One symbol an update changes, and who said so.
 */
export interface ChangedSymbol {
  detail: Detail1;
  kind: Kind1;
  source: Source;
  symbol: Symbol;
  tool: Tool;
  updateId: Updateid;
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
  updateId: Updateid1;
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
  path: Path2;
  snippet: Snippet;
  startLine: Startline;
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
 * A reference that did not survive being re-read.
 */
export interface RefusedReference {
  detail: Detail2;
  line: Line;
  path: Path3;
  reason: Reason;
  updateId: Updateid2;
}
/**
 * An affected file no component could honestly be named for.
 */
export interface UnmappedFile {
  detail: Detail3;
  path: Path4;
  reason: Reason1;
}

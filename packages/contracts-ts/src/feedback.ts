/**
 * Generated from contracts/*.schema.json. Do not edit by hand.
 *
 * Regenerate with: npm run gen:contracts
 * The schemas themselves are generated from the Pydantic models in
 * packages/contracts-py, which are the single author of every artefact shape.
 */

export type Deployversion = number | null;
export type Generatedat = string;
export type Evidence = string;
export type Evidenceref = string;
export type Id = string;
export type Kind = "dependency" | "runtime" | "security";
export type Nodeids = string[];
export type Source = "monitoring" | "risk-assessment" | "release";
export type Suggestedrequirement = string;
export type Summary = string;
export type Traces = string[];
export type Items = FeedbackItem[];
export type Projectid = string;
export type Reportid = string;
export type Sourcereports = string[];

export interface FeedbackReport {
  deployVersion: Deployversion;
  generatedAt: Generatedat;
  items: Items;
  projectId: Projectid;
  reportId: Reportid;
  sourceReports: Sourcereports;
}
export interface FeedbackItem {
  evidence: Evidence;
  evidenceRef: Evidenceref;
  id: Id;
  kind: Kind;
  nodeIds: Nodeids;
  source: Source;
  suggestedRequirement: Suggestedrequirement;
  summary: Summary;
  traces: Traces;
}

/**
 * Generated from contracts/*.schema.json. Do not edit by hand.
 *
 * Regenerate with: npm run gen:contracts
 * The schemas themselves are generated from the Pydantic models in
 * packages/contracts-py, which are the single author of every artefact shape.
 */

export type Contractversion = number;
export type Agreementrate = number;
export type Endpointscalled = number;
export type Endpointsimplemented = number;
export type Endpointsmissing = string[];
export type Endpointstotal = number;
export type Endpointsunused = string[];
export type Foreigncalls = string[];
export type Orphanroutes = string[];
export type Schemamismatches = number;
export type Hint = string;
export type Line = number | null;
export type Path = string;
export type Reason = string;
export type Ruleid = string;
export type Severity = "error" | "warning";
export type Subject = string;
export type Findings = AgreementFinding[];

export interface ContractAgreement {
  contractVersion: Contractversion;
  counts: AgreementCounts;
  findings: Findings;
}
export interface AgreementCounts {
  agreementRate: Agreementrate;
  endpointsCalled: Endpointscalled;
  endpointsImplemented: Endpointsimplemented;
  endpointsMissing: Endpointsmissing;
  endpointsTotal: Endpointstotal;
  endpointsUnused: Endpointsunused;
  foreignCalls: Foreigncalls;
  orphanRoutes: Orphanroutes;
  schemaMismatches: Schemamismatches;
}
export interface AgreementFinding {
  hint: Hint;
  location: CodeLocation | null;
  reason: Reason;
  ruleId: Ruleid;
  severity: Severity;
  subject: Subject;
}
export interface CodeLocation {
  line: Line;
  path: Path;
}

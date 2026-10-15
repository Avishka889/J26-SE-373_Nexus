/**
 * Generated from contracts/*.schema.json. Do not edit by hand.
 *
 * Regenerate with: npm run gen:contracts
 * The schemas themselves are generated from the Pydantic models in
 * packages/contracts-py, which are the single author of every artefact shape.
 */

export type Chosen = "rule" | "llm" | "merged";
/**
 * Canonical keys both arms produced.
 */
export type Agreed = string[];
export type Agreementrate = number;
/**
 * Canonical "METHOD /path".
 */
export type Endpointkey = string;
export type Field = string;
export type Llmvalue = string;
export type Rulevalue = string;
export type Conflicts = ContractConflict[];
export type Attempts = number;
export type Endpoints = number;
export type Errors = number;
export type Warnings = number;
export type Llmonly = string[];
export type Ruleonly = string[];
export type Authactors = string[];
export type Confidence = number;
export type Id = string;
export type Method = "GET" | "POST" | "PUT" | "PATCH" | "DELETE";
export type Origin = "rule" | "llm" | "merged";
export type Path = string;
export type Entity = string;
export type Itemref = string;
export type Maxlength = number | null;
export type Maximum = number | null;
export type Minlength = number | null;
export type Minimum = number | null;
export type Name = string;
export type Oneof = string[];
export type Required = boolean;
export type Rules = string[];
export type Type = "string" | "number" | "boolean" | "date" | "id" | "object" | "array";
export type Fields = SchemaField[];
export type Summary = string;
export type Actionids = string[];
export type Requirementids = string[];
export type Screenids = string[];
export type Storyids = string[];
export type Validation = string[];
export type Endpoints1 = ApiEndpoint[];
export type Fields1 = SchemaField[];
export type Name1 = string;
export type Traces = string[];
export type Entities = EntityModel[];
export type Version = number;
export type Llmfailure = string | null;
export type Reason = string;
export type Ruleid = string;
export type Severity = "error" | "warning";
export type Subject = string;
export type Rulefindings = ContractRuleFinding[];
export type Version1 = number;

/**
 * The stored artefact: both arms, the comparison, and the choice.
 *
 * `contract` is the effective one downstream stages generate from. It equals
 * the chosen arm's output, or the recorded merge. The losing arm is kept
 * whole, because the evaluation compares arms and an artefact that kept only
 * the winner would have destroyed its own denominator.
 */
export interface ApiContractArtefact {
  chosen: Chosen;
  comparison: ArmComparison | null;
  contract: ApiContract;
  llmArm: ApiContract | null;
  llmFailure: Llmfailure;
  ruleArm: ApiContract;
  ruleFindings: Rulefindings;
  version: Version1;
}
/**
 * The ablation data, one run's worth.
 */
export interface ArmComparison {
  agreed: Agreed;
  agreementRate: Agreementrate;
  conflicts: Conflicts;
  llm: ArmCounts;
  llmOnly: Llmonly;
  rule: ArmCounts;
  ruleOnly: Ruleonly;
}
/**
 * The same endpoint, said differently by the two arms. Surfaced as a
 * finding and decided item by item when the human picks merged.
 */
export interface ContractConflict {
  endpointKey: Endpointkey;
  field: Field;
  llmValue: Llmvalue;
  ruleValue: Rulevalue;
}
export interface ArmCounts {
  attempts: Attempts;
  endpoints: Endpoints;
  errors: Errors;
  warnings: Warnings;
}
/**
 * The effective contract one arm produced, or the human's merge.
 */
export interface ApiContract {
  endpoints: Endpoints1;
  entities: Entities;
  version: Version;
}
export interface ApiEndpoint {
  authActors: Authactors;
  confidence: Confidence;
  id: Id;
  method: Method;
  origin: Origin;
  path: Path;
  request: EndpointSchema | null;
  response: EndpointSchema | null;
  summary: Summary;
  traces: EndpointTraces;
  validation: Validation;
}
/**
 * A request or response body, as fields plus the entity it derives from.
 */
export interface EndpointSchema {
  entity: Entity;
  fields: Fields;
}
export interface SchemaField {
  itemRef: Itemref;
  maxLength: Maxlength;
  maximum: Maximum;
  minLength: Minlength;
  minimum: Minimum;
  name: Name;
  oneOf: Oneof;
  required: Required;
  rules: Rules;
  type: Type;
}
/**
 * Where an endpoint comes from. The unit of inference is the user action
 * on a screen, so screens and actions lead; stories and requirements ground
 * them in the plan and the brief.
 */
export interface EndpointTraces {
  actionIds: Actionids;
  requirementIds: Requirementids;
  screenIds: Screenids;
  storyIds: Storyids;
}
/**
 * A data shape the schemas reference, derived from a graph entity.
 */
export interface EntityModel {
  fields: Fields1;
  name: Name1;
  traces: Traces;
}
/**
 * One of the rule catalogue's findings about an arm's contract.
 */
export interface ContractRuleFinding {
  reason: Reason;
  ruleId: Ruleid;
  severity: Severity;
  subject: Subject;
}

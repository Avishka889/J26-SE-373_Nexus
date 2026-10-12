/**
 * Generated from contracts/*.schema.json. Do not edit by hand.
 *
 * Regenerate with: npm run gen:contracts
 * The schemas themselves are generated from the Pydantic models in
 * packages/contracts-py, which are the single author of every artefact shape.
 */

export type Changednodeids = string[];
export type Id = string;
export type Kind = "action" | "data" | "dependency" | "constraint";
export type Source = string;
export type Target = string;
export type Traces = string[];
export type Verb = string;
export type Edges = GraphEdge[];
export type Actorkind = ("primary" | "external_system") | null;
export type Appliesto = string[];
export type Name = string;
export type Type = string;
export type Attributes = EntityAttribute[];
export type Changedinversion = number | null;
export type Description = string;
export type Id1 = string;
export type Kind1 = "actor" | "entity" | "service" | "constraint";
export type Label = string;
export type X = number;
export type Y = number;
export type Standard = string | null;
export type Traces1 = string[];
export type Reason = string;
export type Ruleid = string;
export type Traces2 = string[];
export type Nodes = GraphNode[];

export interface ArchitectureGraph {
  changedNodeIds: Changednodeids;
  edges: Edges;
  nodes: Nodes;
}
export interface GraphEdge {
  id: Id;
  kind: Kind;
  source: Source;
  target: Target;
  traces: Traces;
  verb: Verb;
}
export interface GraphNode {
  actorKind: Actorkind;
  appliesTo: Appliesto;
  attributes: Attributes;
  changedInVersion: Changedinversion;
  description: Description;
  id: Id1;
  kind: Kind1;
  label: Label;
  position: Position;
  standard: Standard;
  traces: Traces1;
  unconfirmed: ValidationFinding | null;
}
export interface EntityAttribute {
  name: Name;
  type: Type;
}
export interface Position {
  x: X;
  y: Y;
}
/**
 * A named rule check that could not confirm a node.
 *
 * Carried on the node itself rather than reported in a separate list, because a
 * warning the reader cannot trace to a cause is worse than no warning: the
 * canvas has to be able to say which rule fired, in plain words, and which
 * requirement the reader should go and look at.
 *
 * `rule_id` is the stable name of one of C1's rule checks, so the same finding
 * can be counted across runs for the evaluation. `reason` is written for the
 * person reading the design, and doubles as the repair hint the extraction loop
 * feeds back to the model.
 */
export interface ValidationFinding {
  reason: Reason;
  ruleId: Ruleid;
  traces: Traces2;
}

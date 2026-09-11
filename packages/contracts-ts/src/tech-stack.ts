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
export type Candidates = [StackCandidate, ...StackCandidate[]];
export type Available = boolean;
export type Explanation = string;
export type Id = string;
/**
 * @minItems 1
 */
export type Layers = [StackLayer, ...StackLayer[]];
export type Choice = string;
export type Name = string;
export type Rationale = string;
export type Version = string;
export type Name1 = string;
export type Score = number;
export type Label = string;
export type Points = number;
export type Scorebreakdown = ScorePart[];
export type Unavailablereason = string | null;
export type Label1 = string;
export type Value = number;
export type Facts = CountedFact[];
export type Recommendedid = string;
export type Selectedat = string | null;
export type Selectedby = string | null;
export type Selectedid = string | null;

export interface TechStackArtefact {
  candidates: Candidates;
  facts: Facts;
  recommendedId: Recommendedid;
  selectedAt: Selectedat;
  selectedBy: Selectedby;
  selectedId: Selectedid;
}
export interface StackCandidate {
  available: Available;
  explanation: Explanation;
  id: Id;
  layers: Layers;
  name: Name1;
  score: Score;
  scoreBreakdown: Scorebreakdown;
  unavailableReason: Unavailablereason;
}
export interface StackLayer {
  choice: Choice;
  name: Name;
  rationale: Rationale;
  version: Version;
}
export interface ScorePart {
  label: Label;
  points: Points;
}
/**
 * One number the scoring rests on, named so a reader can check it.
 */
export interface CountedFact {
  label: Label1;
  value: Value;
}

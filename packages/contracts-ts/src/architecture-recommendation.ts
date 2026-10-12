/**
 * Generated from contracts/*.schema.json. Do not edit by hand.
 *
 * Regenerate with: npm run gen:contracts
 * The schemas themselves are generated from the Pydantic models in
 * packages/contracts-py, which are the single author of every artefact shape.
 */

/**
 * @minItems 2
 */
export type Candidates = [TopologyCandidate, TopologyCandidate, ...TopologyCandidate[]];
/**
 * @minItems 2
 */
export type Cons = [string, string, ...string[]];
export type Id = string;
export type Name = string;
/**
 * @minItems 1
 */
export type Pros = [string, ...string[]];
export type Rationale = string;
export type Score = number;
export type Recommendedcandidateid = string;
export type Selectedat = string | null;
export type Selectedby = string | null;
export type Selectedcandidateid = string | null;
export type Id1 = string;
export type Name1 = string;
export type Note = string;

export interface ArchitectureRecommendation {
  candidates: Candidates;
  recommendedCandidateId: Recommendedcandidateid;
  selectedAt: Selectedat;
  selectedBy: Selectedby;
  selectedCandidateId: Selectedcandidateid;
  style: ArchitectureStyleNote;
}
export interface TopologyCandidate {
  cons: Cons;
  id: Id;
  name: Name;
  pros: Pros;
  rationale: Rationale;
  score: Score;
}
/**
 * A code organisation style: applies inside whichever shape is chosen.
 */
export interface ArchitectureStyleNote {
  id: Id1;
  name: Name1;
  note: Note;
}

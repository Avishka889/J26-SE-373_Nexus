/**
 * Generated from contracts/*.schema.json. Do not edit by hand.
 *
 * Regenerate with: npm run gen:contracts
 * The schemas themselves are generated from the Pydantic models in
 * packages/contracts-py, which are the single author of every artefact shape.
 */

export type Dismissed = boolean;
export type Edited = boolean;
export type Id = string;
export type Text = string;
export type Traces = string[];
export type Assumptions = Assumption[];
export type Answer = string | null;
export type Answeredat = string | null;
export type Id1 = string;
export type Question = string;
export type Traces1 = string[];
export type Questions = ClarifyingQuestion[];
export type Adjusted = boolean;
export type Confidence = number;
export type Id2 = string;
export type Lowconfidence = boolean;
export type Priority = "must" | "should" | "could";
export type Prioritycorrected = boolean;
export type Qualityattribute = ("performance" | "security" | "usability" | "reliability") | null;
export type Setasidecorrection = string | null;
export type Sourcequote = string | null;
export type Text1 = string;
export type Type = "functional" | "quality" | "constraint";
export type Requirements = ParsedRequirement[];

/**
 * What C1's `/requirements` endpoint produces.
 */
export interface RequirementsArtefact {
  assumptions: Assumptions;
  questions: Questions;
  requirements: Requirements;
}
export interface Assumption {
  dismissed: Dismissed;
  edited: Edited;
  id: Id;
  text: Text;
  traces: Traces;
}
export interface ClarifyingQuestion {
  answer: Answer;
  answeredAt: Answeredat;
  id: Id1;
  question: Question;
  traces: Traces1;
}
export interface ParsedRequirement {
  adjusted: Adjusted;
  confidence: Confidence;
  id: Id2;
  lowConfidence: Lowconfidence;
  priority: Priority;
  priorityCorrected: Prioritycorrected;
  qualityAttribute: Qualityattribute;
  setAsideCorrection: Setasidecorrection;
  sourceQuote: Sourcequote;
  text: Text1;
  type: Type;
}

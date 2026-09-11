/**
 * Generated from contracts/*.schema.json. Do not edit by hand.
 *
 * Regenerate with: npm run gen:contracts
 * The schemas themselves are generated from the Pydantic models in
 * packages/contracts-py, which are the single author of every artefact shape.
 */

export type Sprintname = string;
export type Decidedby = string;
export type Id = string;
export type Inscope = boolean;
export type Points = number;
export type Sprint = number;
export type Title = string;
export type Requirementids = string[];
export type Screenids = string[];
export type Stories = ScopeStory[];

export interface SprintScope {
  sprintName: Sprintname;
  stories: Stories;
}
/**
 * One story's place in the build: in or out, and why it maps anywhere.
 */
export interface ScopeStory {
  decidedBy: Decidedby;
  id: Id;
  inScope: Inscope;
  points: Points;
  sprint: Sprint;
  title: Title;
  traces: ScopeStoryTraces;
}
export interface ScopeStoryTraces {
  requirementIds: Requirementids;
  screenIds: Screenids;
}

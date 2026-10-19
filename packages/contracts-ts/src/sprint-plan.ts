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
export type Acceptance = [AcceptanceCriterion, ...AcceptanceCriterion[]];
export type Given = string;
export type Id = string;
export type Then = string;
export type When = string;
export type Epic = string;
export type Id1 = string;
export type Points = number;
export type Priority = "must" | "should" | "could";
export type Title = string;
export type Traces = string[];
export type Backlog = UserStory[];
export type Because = string;
export type Needs = string;
export type Storyid = string;
export type Backlogdependencies = BacklogDependency[];
export type Estimatedpoints = number;
export type Goal = string;
export type Proposed = UserStory[];
export type Sprintname = string;
export type Basis = string;
export type Points1 = number;

export interface SprintPlan {
  backlog: Backlog;
  backlogDependencies: Backlogdependencies;
  estimatedPoints: Estimatedpoints;
  goal: Goal;
  proposed: Proposed;
  sprintName: Sprintname;
  velocityAssumption: VelocityAssumption;
}
export interface UserStory {
  acceptance: Acceptance;
  epic: Epic;
  id: Id1;
  points: Points;
  priority: Priority;
  title: Title;
  traces: Traces;
}
export interface AcceptanceCriterion {
  given: Given;
  id: Id;
  then: Then;
  when: When;
}
/**
 * A story in the sprint that needs one left in the backlog.
 *
 * Read off the design: a requirement the sprint's story realises draws a
 * connection to something nothing in the sprint builds, and a backlog story
 * builds it. The sprint is divided by priority and size alone, so nothing else
 * would say that it cannot be finished as proposed (review item C1-5).
 */
export interface BacklogDependency {
  because: Because;
  needs: Needs;
  storyId: Storyid;
}
export interface VelocityAssumption {
  basis: Basis;
  points: Points1;
}

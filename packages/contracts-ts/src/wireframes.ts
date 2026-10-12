/**
 * Generated from contracts/*.schema.json. Do not edit by hand.
 *
 * Regenerate with: npm run gen:contracts
 * The schemas themselves are generated from the Pydantic models in
 * packages/contracts-py, which are the single author of every artefact shape.
 */

export type Covered = boolean;
export type Needsscreen = boolean;
export type Screenids = string[];
export type Storyid = string;
export type Storytitle = string;
export type Coverage = WireframeCoverageRow[];
export type Coversstoryids = string[];
export type Id = string;
export type Name = string;
export type Pendingrefinement = boolean;
export type Refinementnote = string | null;
/**
 * The screens of this flow. The first is the entry point: the player opens there and the card thumbnail shows it, so ordering is meaning rather than presentation. Every other screen has to be reachable from it by following links.
 *
 * @minItems 1
 */
export type Screens = [FlowScreen, ...FlowScreen[]];
export type Id1 = string;
export type Kind = "field" | "row" | "summary" | "banner" | "text" | "list" | "button" | "display";
export type Label = string;
export type Linkid = string | null;
export type Tone = ("neutral" | "positive" | "muted") | null;
export type Value = string | null;
export type Blocks = ScreenBlock[];
export type Crumbs = string[];
export type Id2 = string;
export type Id3 = string;
export type Label1 = string;
export type Targetid = string;
export type Variant = "primary" | "secondary" | "row" | "text";
export type Links = FlowLink[];
export type Name1 = string;
/**
 * True when this screen is meant to be the end of the journey, such as a confirmation or an error. A screen with no outgoing links is otherwise reported as a dead end, and this is how a flow says the dead end was the point. Assigned by rule from the screen's name and correctable by a human, never written by a generating model: a flag that silences a warning is a flag a model will set to silence the warning.
 */
export type Terminal = boolean;
export type Traces = string[];
export type Version = string;
export type Flows = WireframeFlow[];

export interface WireframesArtefact {
  coverage: Coverage;
  flows: Flows;
}
export interface WireframeCoverageRow {
  covered: Covered;
  needsScreen: Needsscreen;
  screenIds: Screenids;
  storyId: Storyid;
  storyTitle: Storytitle;
}
export interface WireframeFlow {
  coversStoryIds: Coversstoryids;
  id: Id;
  name: Name;
  pendingRefinement: Pendingrefinement;
  refinementNote: Refinementnote;
  screens: Screens;
  traces: Traces;
  version: Version;
}
export interface FlowScreen {
  blocks: Blocks;
  crumbs: Crumbs;
  id: Id2;
  links: Links;
  name: Name1;
  terminal: Terminal;
}
export interface ScreenBlock {
  id: Id1;
  kind: Kind;
  label: Label;
  linkId: Linkid;
  tone: Tone;
  value: Value;
}
export interface FlowLink {
  id: Id3;
  label: Label1;
  targetId: Targetid;
  variant: Variant;
}

/**
 * Generated from contracts/*.schema.json. Do not edit by hand.
 *
 * Regenerate with: npm run gen:contracts
 * The schemas themselves are generated from the Pydantic models in
 * packages/contracts-py, which are the single author of every artefact shape.
 */

export type Description = string;
export type Id = string;
export type Kind = "class" | "er" | "activity" | "sequence";
/**
 * Authored diagram text, when there is any. Null means the diagram is projected from the architecture graph when it is drawn, which is the case for class and entity relationship diagrams: freezing their text here would keep an old name after a node is renamed.
 */
export type Source = string | null;
export type Title = string;
export type Traces = string[];
/**
 * The use case this diagram draws, for sequence diagrams.
 */
export type Usecaseid = string | null;
export type Diagrams = UmlDiagram[];
export type Id1 = string;
export type Name = string;
/**
 * @minItems 1
 */
export type Steps = [SequenceStep, ...SequenceStep[]];
/**
 * Id of the architecture graph node this step goes from.
 */
export type Fromid = string;
/**
 * call for a request, return for an answer, note for an aside.
 */
export type Kind1 = "call" | "return" | "note";
/**
 * What is asked or answered. Names inside the text are written as `{nodeId}` tokens, referring to nodes of the architecture graph, and are replaced with the node's current label when the diagram is drawn. Never write a node's name in as text: the copy would not follow a rename. A token naming no node renders as the literal braces, which is deliberate, since a silently dropped name reads as correct.
 */
export type Message = string;
/**
 * Id of the architecture graph node this step goes to.
 */
export type Toid = string;
export type Storyid = string | null;
export type Traces1 = string[];
export type Usecases = UseCase[];

export interface UmlArtefact {
  diagrams: Diagrams;
  useCases: Usecases;
}
export interface UmlDiagram {
  description: Description;
  id: Id;
  kind: Kind;
  source: Source;
  title: Title;
  traces: Traces;
  useCaseId: Usecaseid;
}
export interface UseCase {
  id: Id1;
  name: Name;
  steps: Steps;
  storyId: Storyid;
  traces: Traces1;
}
export interface SequenceStep {
  fromId: Fromid;
  kind: Kind1;
  message: Message;
  toId: Toid;
}

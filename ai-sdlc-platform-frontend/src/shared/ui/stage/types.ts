/**
 * What a phase has to tell the shared stage chrome about itself.
 *
 * The chrome was written for Requirements and Design and then needed, whole,
 * by Code Generation: the same sticky rail, the same anchor pills, the same
 * pending, generating and failed guards. Copying it would have meant two
 * implementations of the one thing a reader uses to know where they are, so
 * the words and the ids became a parameter instead.
 *
 * A phase supplies its stage ids in order, how to label them, and which blocks
 * each one renders. Everything the chrome does follows from those.
 */

import type { StageModelUse } from "@sdlc/contracts-ts";

/**
 * `skipped` is the one the design and code phases never produce, and it is here
 * rather than in the one phase that does because the chrome is shared: a phase
 * with a state the chrome cannot express is a phase that has to grow its own
 * chrome, which is how the testing phase came to have one.
 *
 * It means the stage had nothing to do on this target, not that it failed and
 * not that it finished. Test generation writes TypeScript from the API
 * contract, so a Java repository gives it nothing to write.
 */
export type StageStatus = "pending" | "generating" | "complete" | "failed" | "skipped";

export type StageMeta = {
  /** The chevron label: short, and no unexplained abbreviations. */
  label: string;
  /** The stage header, which may spell out what the label abbreviates. */
  heading: string;
  /** One line under the heading saying what this stage is for. */
  blurb: string;
};

/** A block of a stage that an anchor can point at. */
export type StageSectionMeta = { id: string; label: string };

/** The stage state the chrome reads. Both phases' snapshots carry these. */
export type StageChromeState = {
  status: StageStatus;
  generatedFromVersion: number;
  error?: string | null;
  /**
   * What the stage said about itself. The chrome reads it only for a skipped
   * stage, where it carries the reason, and a skip that does not say why is
   * indistinguishable from one that quietly did nothing.
   */
  summary?: string | null;
  /**
   * What answered this stage's version, where it asked a model. Said under a
   * complete stage; a stage that asked none, or one from before stages kept
   * it, says nothing rather than a guess.
   */
  modelUse?: StageModelUse | null;
};

export type StageChrome<Id extends string> = {
  /** Every stage, in the order the reader walks them. */
  ids: readonly Id[];
  meta: Record<Id, StageMeta>;
  sections: Record<Id, StageSectionMeta[]>;
  /**
   * What this phase's version counts, in words: "requirements version" for the
   * design phase, "code version" for this one. The chrome says it out loud in
   * the generating and outdated states, and the two phases version on
   * different axes, so a shared wording would be wrong in one of them.
   */
  versionNoun: string;
  /**
   * The stages whose output each stage reads, as the nodes read them. A stage
   * retried alone regenerates only itself, so a stage that reads it says when
   * it was computed from the output that was replaced.
   */
  reads?: Partial<Record<Id, readonly Id[]>>;
};

/** A stage id the server sent, in the phase's own words, or undefined for one it does not have. */
export function stageLabelIn<Id extends string>(
  chrome: StageChrome<Id>,
  id: string | null | undefined,
): string | undefined {
  return id && (chrome.ids as readonly string[]).includes(id) ? chrome.meta[id as Id].label : undefined;
}

export function stageIndexIn<Id extends string>(chrome: StageChrome<Id>, id: Id): number {
  return chrome.ids.indexOf(id);
}

export function nextStageIn<Id extends string>(chrome: StageChrome<Id>, id: Id): Id | null {
  return chrome.ids[stageIndexIn(chrome, id) + 1] ?? null;
}

export function previousStageIn<Id extends string>(chrome: StageChrome<Id>, id: Id): Id | null {
  const index = stageIndexIn(chrome, id);
  return index > 0 ? chrome.ids[index - 1] : null;
}

/**
 * Outdated is computed, never stored.
 *
 * A stage records the version it was generated from. If the phase has moved on
 * since, the stage is behind, and that comparison is the single source of the
 * answer. Storing a boolean would let it disagree with the versions it is
 * supposed to describe.
 */
export function isOutdated(stage: StageChromeState, version: number): boolean {
  return stage.status === "complete" && stage.generatedFromVersion < version;
}

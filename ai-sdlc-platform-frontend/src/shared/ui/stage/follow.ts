/**
 * Which stage the page should open while a run walks through them.
 *
 * The rule is "follow the run, and stop the moment the reader clicks
 * something", because watching is useful only until somebody wants to look at
 * a particular thing, and pulling the page out from under them after that is
 * worse than showing nothing.
 *
 * The part that was wrong is the end. Following was allowed only while a stage
 * said it was generating, and the last stage of a run completes at the exact
 * moment the last generating stage stops: the snapshot that reports the review
 * stage complete is the same snapshot that reports nothing generating. So the
 * follow stopped one stage short every time and never once landed on the
 * review, which is the only stage with a decision on it. `sawGenerating` is
 * what carries the follow across that last step: a run was watched, so its
 * final stage is still part of what the reader is watching.
 */
export function stageToFollow<Id extends string>({
  order,
  isComplete,
  isGenerating,
  sawGenerating,
  userChoseStage,
  followedTo,
}: {
  /** The stages in the order the run walks them. */
  order: readonly Id[];
  isComplete: (id: Id) => boolean;
  /** Something is generating right now. */
  isGenerating: boolean;
  /** Something was generating at some point while this page was open. */
  sawGenerating: boolean;
  /** The reader has picked a stage, so the page is theirs now. */
  userChoseStage: boolean;
  /** Where the follow has already taken them. */
  followedTo: Id | null;
}): Id | null {
  if (userChoseStage) return null;
  if (!isGenerating && !sawGenerating) return null;
  const completed = order.filter(isComplete);
  const last = completed.length > 0 ? completed[completed.length - 1] : null;
  return last && last !== followedTo ? last : null;
}

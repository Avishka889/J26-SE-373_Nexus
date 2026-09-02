/**
 * How a project gets its name and its description from what was submitted.
 *
 * One module because these are the same rule seen twice: both answer "what did
 * the reader actually write", and neither may reach into the body of an attached
 * document. They lived byte identically in two page components before this,
 * comment and all, which a review flagged as a rule that must not drift.
 */

/** Where a name stops. Longer than this and it is a sentence, not a label. */
export const NAME_LIMIT = 48;

/** Where a description stops. About two lines of a project card. */
export const DESCRIPTION_LIMIT = 200;

function firstParagraph(text: string): string {
  return text.split("\n\n")[0]?.trim() || text;
}

export function projectName(typed: string, files: string[]): string {
  const trimmed = typed.trim();
  const source = trimmed ? firstParagraph(trimmed) : (files[0] ?? "");
  // Unreachable while submit is guarded on the composed text being non empty,
  // but a blank project header is a worse way to find that out than a name is.
  if (!source) return "Untitled project";
  return source.length > NAME_LIMIT ? `${source.slice(0, NAME_LIMIT)}…` : source;
}

/**
 * What the reader typed, bounded, or what they attached if they typed nothing.
 *
 * Bounded here at write time rather than clamped at draw time, because storing
 * thousands of characters in a field called `description` is the same category
 * error this change exists to fix, one step smaller. Nothing is lost: project
 * search covers `requirementText` as well, and the full input is in the
 * conversation behind "Show full input".
 *
 * Cuts at a word, not a sentence. A sentence boundary reads better, right up
 * until the text contains an abbreviation: "e.g." looks exactly like the end
 * of a sentence to a naive splitter, so a description could stop there with no
 * sign that anything had been dropped, and abbreviations are ordinary in
 * requirements prose. A rule that is right every time beats one that is
 * prettier most of the time.
 */
export function projectDescription(typed: string, files: string[]): string {
  const trimmed = typed.trim();
  if (!trimmed) return describeSources(files);
  return trimmed.length > DESCRIPTION_LIMIT ? cutAtWord(trimmed) : trimmed;
}

function cutAtWord(text: string): string {
  // Belt and braces, not a live path: the one call site above already checks
  // the length first. Kept so this helper cannot drop a trailing word and
  // append a false truncation mark if it is ever called on its own.
  if (text.length <= DESCRIPTION_LIMIT) return text;
  const slice = text.slice(0, DESCRIPTION_LIMIT);
  const lastSpace = slice.lastIndexOf(" ");
  // A single word longer than the whole cap has no boundary to cut at, so the
  // hard cut stands rather than this returning nothing.
  const kept = lastSpace > 0 ? slice.slice(0, lastSpace) : slice;
  return `${kept.trimEnd()}…`;
}

function describeSources(files: string[]): string {
  if (files.length === 0) return "";
  if (files.length === 1) return `From ${files[0]}`;
  if (files.length === 2) return `From ${files[0]} and ${files[1]}`;
  return `From ${files[0]} and ${files.length - 1} more`;
}

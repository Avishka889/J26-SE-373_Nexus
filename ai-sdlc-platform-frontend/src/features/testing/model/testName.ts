/**
 * A generated test's name, taken apart for a reader.
 *
 * An acceptance test is named with its whole story and its whole criterion:
 * "As a receptionist, I can record a doctor ... US-2 AC-2-1: given ..., when
 * ..., then ...". That is right for a test file, where the name is the
 * criterion, and wrong for a title: it filled seven lines of the decision bar,
 * and three failures of one story read as the same row three times, each cut
 * off before the criterion that tells them apart.
 */
export interface TestLabel {
  /** "US-2 AC-2-1", the story and criterion the test is for; null when the name carries none. */
  ref: string | null;
  /** The story's sentence, when the name leads with one. */
  story: string;
  /** What the test asserts: the criterion, or the whole name when there is no reference. */
  text: string;
}

const REFERENCE = /^([\s\S]*?)\s*\b(US-\d+)\s+(AC-\d+(?:-\d+)*)\s*:\s*([\s\S]*)$/;

export function testLabel(name: string): TestLabel {
  const found = REFERENCE.exec(name);
  if (!found) return { ref: null, story: "", text: name.trim() };
  return { ref: `${found[2]} ${found[3]}`, story: found[1].trim(), text: found[4].trim() };
}

/** What a failing test is called where there is room for a few words. */
export function shortTestName(name: string): string {
  const label = testLabel(name);
  return label.ref ?? label.text;
}

/** What the runner said, without the stack under it. */
export function firstLine(message: string | null | undefined): string {
  return (message ?? "").split("\n")[0].trim();
}

/**
 * The line of the test file a failure's stack passes through, or 0.
 *
 * The runner reports absolute paths inside its own workspace, so the file is
 * matched by its name, which is what the two paths share.
 */
export function lineIn(message: string | null | undefined, path: string): number {
  const name = path.split("/").pop() ?? "";
  if (!name || !message) return 0;
  const escaped = name.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
  const found = new RegExp(`${escaped}:(\\d+)`).exec(message);
  return found ? Number(found[1]) : 0;
}

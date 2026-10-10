/**
 * The header while the design waits on its questions.
 *
 * A run whose analysis asked questions pauses before building the rest, and the
 * page said nothing about it in the one line every phase uses to say what it is
 * doing now.
 */
export function questionsLine(open: number): string {
  if (open === 0) return "Every question is answered: continue with your answers";
  return `Waiting for your answers to ${open === 1 ? "one question" : `${open} questions`}`;
}

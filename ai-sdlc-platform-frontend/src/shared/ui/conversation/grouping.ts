import type { ConversationMessage } from "./types";

export type Item =
  | { kind: "message"; message: ConversationMessage }
  | { kind: "events"; events: ConversationMessage[] };

/** A record with nothing to open, answer or expand: a line and nothing more. */
export function plainRecord(message: ConversationMessage): boolean {
  return (
    message.role === "system" &&
    !message.onOpen &&
    !message.answer &&
    !message.footer &&
    !message.collapsible
  );
}

/** Folded from this many records in a row; fewer read fine as lines. */
const FOLD_FROM = 3;

/**
 * The transcript as it is drawn: every message in order, with runs of plain
 * records folded into one line. Nothing is dropped; a fold opens to its records.
 */
export function grouped(messages: ConversationMessage[]): Item[] {
  const items: Item[] = [];
  let run: ConversationMessage[] = [];
  const flush = () => {
    if (run.length >= FOLD_FROM) items.push({ kind: "events", events: run });
    else run.forEach((message) => items.push({ kind: "message", message }));
    run = [];
  };
  for (const message of messages) {
    if (plainRecord(message)) {
      run.push(message);
      continue;
    }
    flush();
    items.push({ kind: "message", message });
  }
  flush();
  return items;
}

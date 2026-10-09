import type { ReactNode } from "react";

/**
 * One entry in a phase conversation.
 *
 * Deliberately generic: the other phases adopt this panel later, so it knows
 * about people, agents and events, and nothing about requirements or stages. A
 * feature maps its own records into these.
 *
 * Every entry is a real event. There is nothing decorative here, because a
 * transcript with invented turns in it stops being evidence of what happened.
 */
export interface ConversationMessage {
  id: string;
  /** Who spoke. `system` is the platform recording something, not a participant. */
  role: "user" | "agent" | "system";
  author: string;
  content: string;
  /** Preformatted for display: the panel never reformats a timestamp. */
  at: string;
  /** A small label on the message, for example the stage it summarises. */
  chip?: string;
  /** Makes the whole message a link, for example a summary opening its stage. */
  onOpen?: () => void;
  openLabel?: string;
  /**
   * An unanswered question renders its reply box inside the bubble.
   *
   * The affordance belongs with the question because that is what the question
   * is: the agent waiting for a reply. Putting it anywhere else makes the reader
   * hunt for where to answer.
   */
  answer?: {
    placeholder: string;
    pending?: boolean;
    /** A promise keeps the reply in its box until it settles, and there if it fails. */
    onSubmit: (text: string) => void | Promise<unknown>;
  };
  /**
   * Long content collapses to a preview.
   *
   * A pasted requirements document is the first message in the transcript and
   * would otherwise be the only thing on screen.
   */
  collapsible?: boolean;
  /** Rendered under the content, for example the trace chips on an answer. */
  footer?: ReactNode;
}

export interface ConversationComposer {
  placeholder: string;
  /** The one line under the box saying what sending will do. */
  helper: string;
  pending: boolean;
  /**
   * Sends the text. A returned promise keeps the text in the box until it
   * settles: it empties when the send is accepted and stays when it fails, so
   * a refusal never costs the person what they wrote.
   */
  onSubmit: (text: string) => void | Promise<unknown>;
  /**
   * Why sending cannot work right now, for example no review waiting. Shown in
   * place of the helper, and Send stays off until it clears.
   */
  unavailable?: string;
  /**
   * What a send runs on, said under the box: the model and how hard it
   * thinks, as a chat box in other tools names its model. `to` links to where
   * that is chosen, where it can be.
   */
  runsOn?: { text: string; to?: string };
}

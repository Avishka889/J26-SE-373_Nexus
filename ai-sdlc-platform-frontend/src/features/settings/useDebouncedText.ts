import { useEffect, useRef, useState } from "react";
import { messageOf } from "@/lib/http";
import { useUiStore } from "@/store/ui";

/**
 * A text field that types locally and saves once the typing stops.
 *
 * Wired straight to a mutation, an `onChange` sends one request per keystroke:
 * eight characters of an organisation name produced seventeen PATCHes in two
 * and a half seconds in one real session. Those requests race each other over
 * a single row, so what lands is whichever finishes last rather than what was
 * typed, and "vinozhan" came back as "vinoz".
 *
 * A null draft means nobody is typing, and once nothing is being sent either,
 * the server's value is shown. That is what keeps a refetch from overwriting a
 * half typed word, without a ref holding a "dirty" flag beside the state that
 * already says it.
 *
 * Two more things a field owes the person typing: an edit still waiting for
 * the pause when the field goes away (a tab switched, a page left) is sent,
 * not dropped; and a save the server refuses says so, since the field quietly
 * showing the old value again was easy to miss.
 *
 * The third element sends a held edit now, for an action that reads what was
 * typed: saving the Atlas secret within a second of typing an identifier
 * checked the identifier the server still held.
 */
export function useDebouncedText(
  value: string,
  save: (next: string) => void | Promise<unknown>,
  delay = 600,
): [string, (next: string) => void, () => Promise<void>] {
  const addToast = useUiStore((s) => s.addToast);
  const [draft, setDraft] = useState<string | null>(null);
  // What was sent, shown until its save has settled. Dropping it the moment
  // it was sent showed the server's old copy until the answer came, which on
  // the Atlas tab read as the fields clearing themselves.
  const [sending, setSending] = useState<string | null>(null);

  // The newest draft and save, for the unmount below, which must not restart
  // whenever either changes.
  const pending = useRef<{ draft: string | null; send: (text: string) => Promise<unknown> }>({
    draft: null,
    send: async () => undefined,
  });

  const send = (text: string) =>
    Promise.resolve(save(text)).catch((error: unknown) => {
      // A refused save puts the server's copy back, which is how the field shows
      // it; this says it out loud.
      addToast({ type: "error", title: "Not saved", message: messageOf(error) });
    });
  useEffect(() => {
    pending.current = { draft, send };
  });

  useEffect(() => {
    if (draft === null) return;
    const timer = setTimeout(() => {
      const sent = draft;
      setSending(sent);
      setDraft(null);
      void send(sent).finally(() => setSending((now) => (now === sent ? null : now)));
    }, delay);
    return () => clearTimeout(timer);
    // `send` is deliberately not a dependency: the callers build `save` fresh on
    // every render, and depending on it would restart the timer each time and
    // never fire. The draft and the delay are what the timer is about.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [draft, delay]);

  useEffect(
    () => () => {
      // Leaving with an edit the pause has not sent yet: send it now.
      const { draft: held, send: flush } = pending.current;
      if (held !== null) void flush(held);
    },
    [],
  );

  const flush = async () => {
    const held = pending.current.draft;
    if (held === null) return;
    setSending(held);
    setDraft(null);
    await pending.current.send(held);
    setSending((now) => (now === held ? null : now));
  };

  return [draft ?? sending ?? value, setDraft, flush];
}

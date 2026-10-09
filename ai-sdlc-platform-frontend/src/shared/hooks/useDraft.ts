import { useCallback, useSyncExternalStore } from "react";

const drafts = new Map<string, string>();
const listeners = new Set<() => void>();

function subscribe(listener: () => void) {
  listeners.add(listener);
  return () => {
    listeners.delete(listener);
  };
}

/**
 * Text a person is writing, kept by key until it is sent.
 *
 * Held outside any component, so a note survives its box unmounting: a phase
 * renders only its open stage, and a reviewer who leaves a half written note to
 * check the evidence comes back to it. Memory for this tab only, never storage:
 * a draft is not worth a stale copy on another visit. The key names the
 * project and the thing the note is about, so drafts never cross.
 */
export function useDraft(key: string): [string, (text: string) => void] {
  const text = useSyncExternalStore(
    subscribe,
    () => drafts.get(key) ?? "",
    () => "",
  );
  const setText = useCallback(
    (next: string) => {
      if (next) drafts.set(key, next);
      else drafts.delete(key);
      for (const listener of listeners) listener();
    },
    [key],
  );
  return [text, setText];
}

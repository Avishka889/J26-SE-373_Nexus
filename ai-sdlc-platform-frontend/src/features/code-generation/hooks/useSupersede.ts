import { useCallback, useState } from "react";

export interface SupersedeAsk {
  /** The approved code version a new one would replace. */
  version: number;
  run: () => void;
}

/**
 * Asking before a new code version replaces an approved one.
 *
 * `guard` runs the action at once when nothing approved is in the way, and
 * otherwise holds it until the reader confirms; the action is told whether it
 * supersedes, which is what the server needs to hear to allow it.
 */
export function useSupersede() {
  const [ask, setAsk] = useState<SupersedeAsk | null>(null);

  const guard = useCallback(
    (approved: number | null, action: (supersede: boolean) => void) => {
      if (approved === null) {
        action(false);
        return;
      }
      setAsk({ version: approved, run: () => action(true) });
    },
    [],
  );

  const confirm = useCallback(() => {
    ask?.run();
    setAsk(null);
  }, [ask]);

  const cancel = useCallback(() => setAsk(null), []);

  /** A refusal the snapshot did not foresee: ask now, and retry on yes. */
  const askAfterRefusal = useCallback((version: number, retry: () => void) => {
    setAsk({ version, run: retry });
  }, []);

  return { ask, guard, confirm, cancel, askAfterRefusal };
}

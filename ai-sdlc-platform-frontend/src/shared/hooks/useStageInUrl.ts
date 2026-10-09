import { useEffect, useRef } from "react";
import { useSearchParams } from "react-router-dom";

/**
 * The open stage in the address, as `?stage=`, so a reload, a shared link or
 * coming back to the page opens it again.
 *
 * The open stage was each phase's own state, and every reload, every way back
 * and every link a person sent landed on the first stage. Each phase keeps its
 * own rules for which stage opens (following a run, opening what needs a
 * decision); this reads the address once, on arrival, as if the reader had
 * chosen that stage, and writes each change back into the current entry
 * rather than adding one per stage, so the back button still leaves the page.
 */
export function useStageInUrl<Id extends string>(
  current: Id,
  choose: (id: Id) => void,
  ids: readonly Id[],
): void {
  const [params] = useSearchParams();
  // The stage the address asked for on arrival, until the page has opened it.
  const asked = useRef<Id | null | undefined>(undefined);
  if (asked.current === undefined) {
    const named = params.get("stage");
    asked.current = named && (ids as readonly string[]).includes(named) ? (named as Id) : null;
  }

  useEffect(() => {
    const wanted = asked.current;
    if (wanted && wanted !== current) {
      choose(wanted);
      return;
    }
    asked.current = null;
    // Written through the history API, not as a router navigation: a
    // navigation renders the whole page again, which on a stage full of screen
    // previews outlasted the section pills' first light. The router reads the
    // address again on a reload or a way back, which is all this is for, and
    // the entry keeps the router's own state.
    const address = new URL(window.location.href);
    if (address.searchParams.get("stage") === current) return;
    address.searchParams.set("stage", current);
    window.history.replaceState(window.history.state, "", address);
  }, [choose, current]);
}

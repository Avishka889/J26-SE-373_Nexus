import { useSyncExternalStore } from "react";
import { getSession, subscribeSession, type Session } from "./api";

/** Where this tab's sign-in stands, re-rendering when it changes. */
export function useSession(): Session {
  return useSyncExternalStore(subscribeSession, getSession, getSession);
}

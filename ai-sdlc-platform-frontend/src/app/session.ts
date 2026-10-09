import { queryClient } from "@/app/queryClient";
import { signOut } from "@/entities/account";
import { forgetProjects } from "@/entities/project";
import { forgetConnections, forgetSettings } from "@/entities/settings";
import { useSessionStore } from "@/store/session";

/**
 * Drop everything read for the account that was signed in.
 *
 * Projects, settings, connections and every cached phase snapshot belong to
 * one account; a tab that signs out and back in as someone else must read
 * theirs, not show the last one's until the reads land.
 */
export function forgetAccountData(): void {
  forgetProjects();
  forgetSettings();
  forgetConnections();
  queryClient.clear();
  useSessionStore.getState().clearSession();
}

/** Sign out on the server and forget the account's data. */
export async function signOutAndForget(): Promise<void> {
  try {
    await signOut();
  } finally {
    forgetAccountData();
  }
}

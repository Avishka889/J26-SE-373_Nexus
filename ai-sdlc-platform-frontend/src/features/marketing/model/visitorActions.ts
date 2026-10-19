import { isSignedIn, useSession } from "@/entities/account";

export interface VisitorAction {
  label: string;
  to: string;
}

/**
 * What the landing page offers, by who is looking.
 *
 * A visitor who is signed out is offered an account and the way in. One who is
 * signed in is offered the workspace and nothing else: "Sign in" took them
 * straight past the sign-in page, which read as a broken button. While the
 * server is still being asked, the page reads as signed out, so it paints at
 * once.
 */
export function useVisitorActions(): { primary: VisitorAction; secondary: VisitorAction | null } {
  const session = useSession();
  if (isSignedIn(session)) {
    return { primary: { label: "Open workspace", to: "/workspace" }, secondary: null };
  }
  return {
    primary: { label: "Get started", to: "/register" },
    secondary: { label: "Sign in", to: "/login" },
  };
}

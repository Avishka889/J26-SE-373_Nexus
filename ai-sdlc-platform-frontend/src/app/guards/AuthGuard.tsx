import { useEffect, type ReactNode } from "react";
import { Navigate, useLocation } from "react-router-dom";
import { isSignedIn, useSession } from "@/entities/account";
import { hydrateProjects, useProjectsLoad } from "@/entities/project";
import { PageLoader } from "@/shared/ui/Spinner";

/**
 * The signed-in part of the app.
 *
 * It waits for the server to say who is signed in, sends anyone who is not to
 * sign-in with the page they asked for, so a shared link opens after signing
 * in rather than at the home page, and reads the project list only once
 * someone is signed in: the list is theirs, and nobody else's to download.
 */
export function AuthGuard({ children }: { children: ReactNode }) {
  const session = useSession();
  const location = useLocation();
  const load = useProjectsLoad();
  const signedIn = isSignedIn(session);

  useEffect(() => {
    if (signedIn && load.status === "loading") {
      // A failure is recorded in the list's load state, where the lists and
      // the project guard say so with a retry.
      void hydrateProjects().catch(() => undefined);
    }
  }, [signedIn, load.status]);

  if (session.status === "checking") {
    return <PageLoader label="Checking your sign-in" className="min-h-screen" />;
  }
  if (!signedIn) {
    return <Navigate to="/login" replace state={{ from: location.pathname + location.search }} />;
  }
  return <>{children}</>;
}

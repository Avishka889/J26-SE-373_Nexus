import { useEffect, type ReactNode } from "react";
import { Navigate, useLocation } from "react-router-dom";
import { isSignedIn, useSession } from "@/entities/account";
import { hydrateProjects, useProjectsLoad } from "@/entities/project";
import { useSettingsLoad } from "@/entities/settings";
import { PageLoader } from "@/shared/ui/Spinner";

/**
 * The signed-in part of the app.
 *
 * It waits for the server to say who is signed in, sends anyone who is not to
 * sign-in with the page they asked for, so a shared link opens after signing
 * in rather than at the home page, and reads the project list only once
 * someone is signed in: the list is theirs, and nobody else's to download.
 *
 * It then holds the page until the account's settings are read, which is one
 * small request: the shell drew "Hi there" and blank settings for a moment and
 * then filled itself in. The project list is not waited for, because it is the
 * slow read; the lists draw their own places while it arrives.
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
  return <AccountReady>{children}</AccountReady>;
}

/**
 * Rendered only for someone signed in, because looking at the settings is
 * what asks the server for them. A read that failed does not hold the page:
 * Settings says so itself, with a retry.
 */
function AccountReady({ children }: { children: ReactNode }) {
  const settings = useSettingsLoad();
  if (!settings.loaded && !settings.error) {
    return <PageLoader label="Loading your workspace" className="min-h-screen" />;
  }
  return <>{children}</>;
}

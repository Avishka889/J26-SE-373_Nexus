import { useEffect, type ReactNode } from "react";
import { BrowserRouter } from "react-router-dom";
import { QueryClientProvider } from "@tanstack/react-query";
import { ErrorBoundary } from "@/app/errors/ErrorBoundary";
import { ThemeProvider } from "@/shared/theme";
import { setUnauthorizedHandler } from "@/lib/http";
import { queryClient } from "@/app/queryClient";
import { useUiStore } from "@/store/ui";
import { checkSession, sessionEnded } from "@/entities/account";
import { forgetAccountData } from "@/app/session";

function ThemeBridge({ children }: { children: ReactNode }) {
  const theme = useUiStore((s) => s.theme);
  return <ThemeProvider theme={theme}>{children}</ThemeProvider>;
}

function UnauthorizedBridge({ children }: { children: ReactNode }) {
  useEffect(() => {
    // A request needing a session was answered 401: the session ended on the
    // server. The account's data goes, and the sign-in guard, which watches the
    // session, sends the page to sign-in with a way back to where it was.
    setUnauthorizedHandler(() => {
      sessionEnded();
      forgetAccountData();
    });
    return () => setUnauthorizedHandler(null);
  }, []);
  return <>{children}</>;
}

export function AppProviders({ children }: { children: ReactNode }) {
  // Who is signed in, asked once. Nothing waits for it but the signed-in
  // routes, whose guard shows a loader until it is known: the landing page and
  // the sign-in page paint at once. The project list used to be read here,
  // before any route rendered, which made a visitor to the public landing page
  // watch a spinner for six seconds while the owner's private list downloaded.
  useEffect(() => {
    void checkSession();
  }, []);

  return (
    <ErrorBoundary>
      <QueryClientProvider client={queryClient}>
        <UnauthorizedBridge>
          <ThemeBridge>
            <BrowserRouter>{children}</BrowserRouter>
          </ThemeBridge>
        </UnauthorizedBridge>
      </QueryClientProvider>
    </ErrorBoundary>
  );
}

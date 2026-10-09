import type { ReactNode } from "react";
import { useDocumentTitle } from "@/shared/hooks";
import { Link, Navigate, useLocation } from "react-router-dom";
import { ArrowLeft } from "lucide-react";
import { isSignedIn, useSession } from "@/entities/account";
import { isLive } from "@/lib/env";
import { GlassCard, NexusWordmark } from "@/shared/ui";
import { ThemeProvider } from "@/shared/theme";
import { LoginForm, RegisterForm } from "./components";

function AuthFrame({
  title,
  subtitle,
  children,
  footer,
}: {
  title: string;
  subtitle: string;
  children: ReactNode;
  footer: ReactNode;
}) {
  return (
    <div className="relative flex min-h-screen items-center justify-center bg-white px-4 py-8 sm:px-6 sm:py-12">
      <div className="pointer-events-none absolute inset-0 overflow-hidden">
        <div className="absolute -left-40 top-0 h-[500px] w-[500px] rounded-full bg-blue-400/20 blur-[120px]" />
        <div className="absolute -right-20 bottom-0 h-[400px] w-[400px] rounded-full bg-cyan-300/15 blur-[100px]" />
      </div>

      <div className="relative w-full max-w-md">
        <GlassCard className="bg-white/80 p-5 shadow-blue-900/[0.06] hover:border-white/60 hover:shadow-xl sm:p-8 md:p-10">
          <Link
            to="/"
            className="mb-5 inline-flex items-center gap-1.5 text-sm font-medium text-slate-500 transition-colors hover:text-blue-600 sm:mb-6"
          >
            <ArrowLeft className="h-4 w-4" />
            Back
          </Link>

          <div className="mb-6 text-center sm:mb-8">
            <Link to="/" className="inline-flex justify-center">
              <NexusWordmark className="h-10 max-w-[200px] sm:h-12 sm:max-w-[220px]" />
            </Link>
            <h1 className="mt-5 text-xl font-semibold tracking-tight text-slate-900 sm:mt-6 sm:text-2xl">{title}</h1>
            <p className="mt-2 text-sm text-slate-500">{subtitle}</p>
          </div>

          {/* The sign-in card is light whatever the app's theme: its fields
              followed the dark theme and drew light labels on white. */}
          <ThemeProvider theme="light">{children}</ThemeProvider>

          <div className="mt-6 text-center text-sm text-slate-500">{footer}</div>
        </GlassCard>
      </div>
    </div>
  );
}

/** Where to go after signing in: the page that sent the reader here, or home. */
function useReturnPath(): string {
  const location = useLocation();
  const from = (location.state as { from?: unknown } | null)?.from;
  return typeof from === "string" && from.startsWith("/") && !from.startsWith("/login") ? from : "/workspace";
}

export function Login() {
  useDocumentTitle("Sign in");
  const session = useSession();
  const from = useReturnPath();
  if (isSignedIn(session)) return <Navigate to={from} replace />;

  return (
    <AuthFrame
      title="Welcome back"
      subtitle="Sign in to your AI workspace"
      footer={
        !isLive("projects") ? (
          <span className="text-xs text-slate-500">Demo mode: any email and password will sign you in.</span>
        ) : session.status === "unsupported" ? (
          <span className="text-xs text-slate-500">
            This server does not have sign-in yet, so any email and password open the workspace.
          </span>
        ) : (
          <>
            New here?{" "}
            <Link to="/register" className="font-medium text-blue-700 hover:underline">
              Create an account
            </Link>
          </>
        )
      }
    >
      <LoginForm from={from} />
    </AuthFrame>
  );
}

export function Register() {
  useDocumentTitle("Create an account");
  const session = useSession();
  if (isSignedIn(session)) return <Navigate to="/workspace" replace />;

  return (
    <AuthFrame
      title="Create your account"
      subtitle="Your projects, decisions and connections are kept under it"
      footer={
        <>
          Already have an account?{" "}
          <Link to="/login" className="font-medium text-blue-700 hover:underline">
            Log in
          </Link>
        </>
      }
    >
      <RegisterForm />
    </AuthFrame>
  );
}

export default Login;

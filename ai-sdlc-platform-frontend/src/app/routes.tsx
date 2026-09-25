import { lazy, Suspense, type ReactNode } from "react";
import { Navigate, Route, Routes, useParams } from "react-router-dom";
import { AppShell } from "@/app/layout/AppShell";
import { PageLoader } from "@/shared/ui/Spinner";
import { ProjectShell } from "@/app/layout/ProjectShell";
import { CommandPalette, Toasts } from "@/app/layout/Overlays";
import { AuthGuard } from "@/app/guards/AuthGuard";
import { ProjectGuard } from "@/app/guards/ProjectGuard";
import { projectHomePath, useProject } from "@/entities/project";
import { Landing } from "@/features/marketing";
import { Login, Register } from "@/features/auth";
import { NotFound } from "@/app/errors/NotFound";
import { Home, Projects, NewProject } from "@/features/projects";

const SettingsPage = lazy(() => import("@/features/settings"));
const RequirementsPage = lazy(() => import("@/features/requirements"));
const CodeGeneration = lazy(() => import("@/features/code-generation"));
const TestingSecurity = lazy(() => import("@/features/testing"));
const DeploymentDependency = lazy(() => import("@/features/deployment"));
const ActivityLog = lazy(() => import("@/features/activity"));

function RouteFallback() {
  return (
    <PageLoader className="min-h-[40vh] p-8" />
  );
}

function Lazy({ children }: { children: ReactNode }) {
  return <Suspense fallback={<RouteFallback />}>{children}</Suspense>;
}

/** A project's address with no phase, or an unknown one: the phase its work is in. */
function ProjectPhaseRedirect() {
  const { projectId } = useParams();
  const project = useProject(projectId);
  return (
    <ProjectGuard>{project && <Navigate to={projectHomePath(project)} replace />}</ProjectGuard>
  );
}

function GuardedProject({ children }: { children: ReactNode }) {
  return (
    <ProjectGuard>
      <ProjectShell>
        <Lazy>{children}</Lazy>
      </ProjectShell>
    </ProjectGuard>
  );
}

function AuthenticatedApp() {
  return (
    <AuthGuard>
      <AppShell>
        <Routes>
          <Route path="/workspace" element={<Home />} />
          <Route path="/projects" element={<Projects />} />
          <Route path="/projects/new" element={<NewProject />} />
          <Route
            path="/projects/:projectId/requirements"
            element={
              <GuardedProject>
                <RequirementsPage />
              </GuardedProject>
            }
          />
          {/* No padding wrapper on Code Generation, Testing or Deployment. Each
              is a fixed height two column phase like Requirements and Design:
              its root is `h-full`, which resolves against the shell's bounded
              row only when nothing auto-height sits between them. Inside the
              `p-2` div each had before, the workspace grew to its whole content
              height (7518px measured on Code Generation, 1901px on a live
              testing page, in an 844px main) and the stage column never
              scrolled at all; its `overscroll-contain` kept the wheel from the
              shell as well. Activity is an ordinary page that scrolls in the
              shell, so it keeps its padding. */}
          <Route
            path="/projects/:projectId/code"
            element={
              <GuardedProject>
                <CodeGeneration />
              </GuardedProject>
            }
          />
          <Route
            path="/projects/:projectId/testing"
            element={
              <GuardedProject>
                <TestingSecurity />
              </GuardedProject>
            }
          />
          <Route
            path="/projects/:projectId/deployment"
            element={
              <GuardedProject>
                <DeploymentDependency />
              </GuardedProject>
            }
          />
          <Route
            path="/projects/:projectId/traceability"
            element={
              <GuardedProject>
                <div className="p-2">
                  <ActivityLog />
                </div>
              </GuardedProject>
            }
          />
          <Route path="/projects/:projectId/*" element={<ProjectPhaseRedirect />} />
          <Route
            path="/settings"
            element={
              <Lazy>
                <SettingsPage />
              </Lazy>
            }
          />
          <Route path="*" element={<NotFound />} />
        </Routes>
      </AppShell>
      <CommandPalette />
      <Toasts />
    </AuthGuard>
  );
}

export function AppRoutes() {
  return (
    <Routes>
      <Route path="/" element={<Landing />} />
      <Route path="/login" element={<Login />} />
      <Route path="/register" element={<Register />} />
      <Route path="/*" element={<AuthenticatedApp />} />
    </Routes>
  );
}

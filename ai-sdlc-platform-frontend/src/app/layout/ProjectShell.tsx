import type { ReactNode } from "react";
import { Link, Navigate, useParams, useLocation } from "react-router-dom";
import { CheckCircle2, Code2, FileText, FlaskConical, GitBranch, Rocket } from "lucide-react";
import { useAttention } from "@/entities/attention";
import { useDocumentTitle } from "@/shared/hooks";
import { env } from "@/lib/env";
import { ProjectTitle } from "./ProjectTitle";
import { TAB_PHASE, TAB_STATE_WORDS, tabState } from "./phaseTabs";
import type { Project } from "@/types/project";
import { useProject as useProjectById } from "@/features/projects";
import { useUiStore } from "@/store/ui";
import { cn } from "@/shared/utils/cn";
import { Badge } from "@/shared/ui/primitives";
import { RunStoppedChip } from "@/shared/ui/RunStoppedChip";

function statusBadge(status: Project["status"]) {
  switch (status) {
    case "draft":
      return { label: "Draft", variant: "default" as const };
    case "analyzing":
      return { label: "Analyzing", variant: "info" as const };
    case "design":
      return { label: "Design", variant: "c1" as const };
    case "code":
      return { label: "Code", variant: "c2" as const };
    case "testing":
      return { label: "Testing", variant: "c3" as const };
    case "deploy":
      return { label: "Deploy", variant: "c4" as const };
    case "complete":
      return { label: "Complete", variant: "success" as const };
    default:
      return { label: status, variant: "default" as const };
  }
}

/** Each page under a project, by its address, as its tab names it. */
const PAGE_LABELS: [string, string][] = [
  ["requirements", "Requirements & Design"],
  ["code", "Code Generation"],
  ["testing", "Testing & Security"],
  ["deployment", "Deployment"],
  ["traceability", "Activity Log"],
];

/** The overall figure's four quarters, named as the phase tabs name them. */
const PHASE_SHARES = [
  ["design", "Requirements & Design"],
  ["code", "Code Generation"],
  ["testing", "Testing & Security"],
  ["deployment", "Deployment"],
] as const;

function useShellProject() {
  const { projectId } = useParams();
  const project = useProjectById(projectId);
  return { projectId: projectId!, project };
}

function ProjectShell({ children }: { children: ReactNode }) {
  const { project, projectId } = useShellProject();
  const theme = useUiStore((s) => s.theme);
  const isDark = theme === "dark";
  const location = useLocation();
  const locationPath = location.pathname;
  // What waits on the reader, phase by phase, for the tabs; the server's, so
  // not asked of fixtures.
  const attention = useAttention(!env.allFixtures);
  // The tab title names the phase and the project: "Testing & Security, Book Tracker".
  const pageLabel = PAGE_LABELS.find(([segment]) => locationPath.includes(`/${segment}`))?.[1];
  useDocumentTitle(project ? [pageLabel, project.name].filter(Boolean).join(", ") : null);

  if (!project) return <Navigate to="/projects" replace />;

  const tabs = [
    {
      id: "requirements",
      label: "Requirements & Design",
      path: `/projects/${projectId}/requirements`,
      icon: FileText,
    },
    {
      id: "code",
      label: "Code Generation",
      path: `/projects/${projectId}/code`,
      icon: Code2,
    },
    {
      id: "testing",
      label: "Testing & Security",
      path: `/projects/${projectId}/testing`,
      icon: FlaskConical,
    },
    {
      id: "deployment",
      label: "Deployment",
      path: `/projects/${projectId}/deployment`,
      icon: Rocket,
    },
    {
      id: "traceability",
      label: "Activity Log",
      path: `/projects/${projectId}/traceability`,
      icon: GitBranch,
    },
  ];

  const status = statusBadge(project.status);
  // Where the overall figure comes from, for a reader who hovers it.
  const phases = project.phaseProgress;
  const breakdown = phases
    ? PHASE_SHARES.map(([key, label]) => `${label}: ${phases[key]}%`).join("\n")
    : undefined;
  // A project without a description says so, as the projects list does, rather
  // than borrowing a line about the platform that reads as this project's.
  const description = project.description.trim() || "No description yet";

  return (
    // h-full, not min-h-full. The phase below owns the scrolling now, so this
    // column must be exactly the height of the scrollport rather than growing
    // with its content. min-h-full let the page scroll and put the phase's own
    // columns partly below the fold.
    <div className="flex h-full flex-col overflow-hidden">
      {/* Main project header */}
      <div
        className={cn(
          "shrink-0 border-b px-6 py-5 md:px-8",
          isDark
            ? "border-white/[0.06] bg-[#0a1628]/40"
            : "border-slate-200/80 bg-white/80",
        )}
      >
        <div className="flex flex-wrap items-start gap-4">
          <span
            className="flex h-12 w-12 shrink-0 items-center justify-center rounded-2xl text-sm font-bold text-white shadow-md"
            style={{ backgroundColor: project.color }}
          >
            {project.name.charAt(0)}
          </span>
          <div className="min-w-0 flex-1">
            <div className="flex flex-wrap items-center gap-3">
              <ProjectTitle projectId={project.id} name={project.name} isDark={isDark} />
              <Badge variant={status.variant}>{status.label}</Badge>
              {project.runStopped && <RunStoppedChip />}
            </div>
            <p
              className={cn(
                "mt-1.5 line-clamp-3 max-w-3xl text-sm leading-relaxed",
                isDark ? "text-slate-400" : "text-slate-600",
              )}
            >
              {description}
            </p>
            {project.techStack.length > 0 && (
              <p
                className={cn(
                  "mt-2 text-xs",
                  isDark ? "text-slate-400" : "text-slate-500",
                )}
              >
                {project.techStack.join(" · ")}
              </p>
            )}
          </div>
          <div className="text-right" title={breakdown}>
            <p
              className={cn(
                "text-2xl font-bold tabular-nums",
                isDark ? "text-white" : "text-slate-900",
              )}
            >
              {project.progress}%
            </p>
            <p
              className={cn(
                "text-xs",
                isDark ? "text-slate-400" : "text-slate-500",
              )}
            >
              Overall progress
            </p>
          </div>
        </div>
      </div>

      {/* Phase navigation */}
      <div
        className={cn(
          // No longer sticky: it cannot scroll away, because the region below
          // it scrolls instead of the page.
          "z-20 shrink-0 border-b backdrop-blur-xl md:px-8",
          isDark
            ? "border-white/[0.06] bg-[#071018]/95"
            : "border-slate-200/80 bg-white/95",
        )}
      >
        <nav className="-mb-px flex gap-0 overflow-x-auto px-4 md:px-0">
          {tabs.map((t) => {
            const Icon = t.icon;
            const active = locationPath.includes(`/${t.id}`);
            const phase = TAB_PHASE[t.id as keyof typeof TAB_PHASE];
            const state = phase ? tabState(phase, project, attention) : null;
            return (
              <Link
                key={t.id}
                to={t.path}
                aria-current={active ? "page" : undefined}
                title={state ? `${t.label}: ${TAB_STATE_WORDS[state]}` : undefined}
                className={cn(
                  "group relative flex shrink-0 items-center gap-2.5 border-b-2 px-4 py-3.5 text-[13px] font-medium transition-all",
                  active
                    ? isDark
                      ? "border-blue-500 text-blue-400"
                      : "border-blue-600 text-blue-700"
                    : isDark
                      ? "border-transparent text-slate-400 hover:border-white/10 hover:text-slate-300"
                      : "border-transparent text-slate-500 hover:border-slate-200 hover:text-slate-800",
                )}
              >
                <span
                  className={cn(
                    "flex h-7 w-7 items-center justify-center rounded-lg transition-colors",
                    active
                      ? isDark
                        ? "bg-blue-500/15 text-blue-400"
                        : "bg-blue-50 text-blue-600"
                      : isDark
                        ? "text-slate-400 group-hover:bg-white/[0.04] group-hover:text-slate-400"
                        : "text-slate-500 group-hover:bg-slate-100 group-hover:text-slate-600",
                  )}
                >
                  <Icon className="h-3.5 w-3.5" />
                </span>
                <span className={cn(active && "font-semibold")}>{t.label}</span>
                {state === "done" && (
                  <CheckCircle2 aria-hidden="true" className="h-3.5 w-3.5 text-emerald-700 dark:text-emerald-400" />
                )}
                {state === "waiting" && <span aria-hidden="true" className="h-2 w-2 rounded-full bg-amber-500" />}
                {state === "stopped" && <span aria-hidden="true" className="h-2 w-2 rounded-full bg-red-500" />}
                {state && <span className="sr-only">, {TAB_STATE_WORDS[state]}</span>}
              </Link>
            );
          })}
        </nav>
      </div>

      {/* The scrollport for a phase. min-h-0 is what lets a flex child be
          shorter than its content; without it the child takes its content height
          and the overflow reappears on the page.

          Every other phase scrolls here, as it always did. The design workspace
          is exactly this height and scrolls inside its own two columns, so this
          never scrolls for it. */}
      <div className="min-h-0 flex-1 overflow-y-auto overscroll-contain">
        {children}
      </div>
    </div>
  );
}

export { ProjectShell };

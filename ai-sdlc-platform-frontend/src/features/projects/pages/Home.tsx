import { useEffect } from "react";
import { useDocumentTitle } from "@/shared/hooks";
import { useNavigate } from "react-router-dom";
import {
  Plus,
  FolderKanban,
  ArrowRight,
  Clock,
  CheckCircle2,
  Rocket,
  Code2,
  FlaskConical,
  Pencil,
} from "lucide-react";
import type { Project } from "@/types/project";
import { useSessionStore } from "@/store/session";
import { useUiStore } from "@/store/ui";
import { useCreateFromPrompt, useProjectsList } from "../hooks";
import {
  getProjectsLoad,
  hydrateProjects,
  projectHomePath,
  useProjectsLoad,
} from "@/entities/project";
import { ServerUnavailable } from "@/shared/ui/ServerUnavailable";
import { PageLoader } from "@/shared/ui/Spinner";
import { useSettings } from "@/entities/settings";
import { cn } from "@/shared/utils/cn";
import { Badge, Button, Card, CardContent } from "@/shared/ui/primitives";
import { RunStoppedChip } from "@/shared/ui/RunStoppedChip";
import { ProjectCreatePrompt } from "../components/ProjectCreatePrompt";
import { SpinnerIcon } from "@/shared/ui/Spinner";

function statusMeta(status: Project["status"]) {
  switch (status) {
    case "draft":
      return { label: "Draft", variant: "default" as const, icon: Pencil };
    case "analyzing":
      return { label: "Analyzing", variant: "info" as const, icon: SpinnerIcon };
    case "design":
      return { label: "Design", variant: "c1" as const, icon: Pencil };
    case "code":
      return { label: "Code", variant: "c2" as const, icon: Code2 };
    case "testing":
      return { label: "Testing", variant: "c3" as const, icon: FlaskConical };
    case "deploy":
      return { label: "Deploy", variant: "c4" as const, icon: Rocket };
    case "complete":
      return { label: "Complete", variant: "success" as const, icon: CheckCircle2 };
    default:
      return { label: status, variant: "default" as const, icon: FolderKanban };
  }
}

function formatRelative(iso: string) {
  const diff = Date.now() - new Date(iso).getTime();
  const mins = Math.floor(diff / 60000);
  if (mins < 1) return "just now";
  if (mins < 60) return `${mins}m ago`;
  const hours = Math.floor(mins / 60);
  if (hours < 24) return `${hours}h ago`;
  return `${Math.floor(hours / 24)}d ago`;
}

function stageColors(progress: number) {
  const filled = Math.max(1, Math.min(4, Math.ceil(progress / 25)));
  return Array.from({ length: 4 }, (_, i) => {
    if (i < filled - 1) return "#22c55e";
    if (i === filled - 1) return progress >= 100 ? "#22c55e" : "#2563eb";
    return undefined;
  });
}

export function Home() {
  useDocumentTitle("Home");
  // Statuses move while the reader is elsewhere, and the list was read once,
  // at sign-in. Read again on opening; a list that was read stays if this fails.
  useEffect(() => {
    if (getProjectsLoad().status === "loaded") void hydrateProjects().catch(() => undefined);
  }, []);
  const navigate = useNavigate();
  const theme = useUiStore((s) => s.theme);
  const setActiveProjectId = useSessionStore((s) => s.setActiveProjectId);
  const settings = useSettings();
  const projects = useProjectsList();
  const load = useProjectsLoad();
  const handleCreate = useCreateFromPrompt();
  const isDark = theme === "dark";
  const firstName = settings.profile.name.split(" ")[0] || "there";
  const featured = projects.slice(0, 3);

  const openProject = (p: Project) => {
    setActiveProjectId(p.id);
    navigate(projectHomePath(p));
  };

  return (
    <div className="relative w-full px-4 pb-12 pt-8 sm:px-6 md:px-8 md:pt-14">
        <ProjectCreatePrompt firstName={firstName} isDark={isDark} onSubmit={handleCreate} />

        {/* Active projects */}
        <div className="mt-14">
          <div className="mb-4 flex flex-col gap-3 sm:flex-row sm:items-end sm:justify-between">
            <div>
              <h2 className={cn("text-lg font-semibold tracking-tight", isDark ? "text-white" : "text-slate-900")}>
                Your projects
              </h2>
              <p className={cn("mt-0.5 text-sm", isDark ? "text-slate-400" : "text-slate-500")}>
                Continue a run or start something new
              </p>
            </div>
            <Button variant="outline" size="sm" className="w-full sm:w-auto" onClick={() => navigate("/projects")}>
              View all
              <ArrowRight className="h-3.5 w-3.5" />
            </Button>
          </div>

          {featured.length === 0 && load.status === "failed" ? (
            <ServerUnavailable
              title="Your projects could not be loaded"
              message={load.error ?? ""}
              onRetry={hydrateProjects}
            />
          ) : featured.length === 0 && load.status === "loading" ? (
            <PageLoader label="Loading your projects" className="py-14" />
          ) : featured.length === 0 ? (
            <Card>
              <CardContent className="flex flex-col items-center py-14 text-center">
                <FolderKanban className={cn("mb-3 h-8 w-8", isDark ? "text-slate-400" : "text-slate-300")} />
                <p className={cn("text-sm font-medium", isDark ? "text-slate-300" : "text-slate-700")}>No projects yet</p>
                <p className={cn("mt-1 text-xs", isDark ? "text-slate-400" : "text-slate-500")}>
                  Create your first project to start the SDLC pipeline
                </p>
                <Button variant="primary" size="sm" className="mt-4" onClick={() => navigate("/projects/new")}>
                  <Plus className="h-3.5 w-3.5" />
                  New project
                </Button>
              </CardContent>
            </Card>
          ) : (
            <div className="grid grid-cols-1 gap-4 md:grid-cols-3">
              {featured.map((p) => {
                const st = statusMeta(p.status);
                const stages = stageColors(p.progress);
                return (
                  <Card
                    key={p.id}
                    className={cn(
                      "group cursor-pointer overflow-hidden transition-all hover:-translate-y-0.5",
                      isDark ? "hover:border-white/15" : "hover:border-slate-300 hover:shadow-md"
                    )}
                    onClick={() => openProject(p)}
                  >
                    <div
                      className="relative h-24"
                      style={{
                        background: `linear-gradient(135deg, ${p.color}22 0%, ${p.color}55 50%, ${p.color}33 100%)`,
                      }}
                    >
                      <div className="absolute inset-0 bg-[radial-gradient(circle_at_80%_20%,rgba(255,255,255,0.25),transparent_50%)]" />
                      <div className="absolute bottom-3 left-4 flex h-9 w-9 items-center justify-center rounded-xl bg-white/95 text-sm font-bold text-slate-800 shadow-sm">
                        {p.name.charAt(0)}
                      </div>
                    </div>
                    <CardContent className="space-y-3 p-4">
                      <div className="flex items-start justify-between gap-2">
                        <div className="min-w-0">
                          <h3 className={cn("truncate text-sm font-semibold", isDark ? "text-white" : "text-slate-900")}>
                            {p.name}
                          </h3>
                          <p className={cn("mt-0.5 line-clamp-2 text-xs leading-relaxed", isDark ? "text-slate-400" : "text-slate-500")}>
                            {p.description}
                          </p>
                        </div>
                        <span className="flex shrink-0 flex-wrap justify-end gap-1">
                          <Badge variant={st.variant}>{st.label}</Badge>
                          {p.runStopped && <RunStoppedChip />}
                        </span>
                      </div>

                      <div className="flex gap-1">
                        {stages.map((color, i) => (
                          <div
                            key={i}
                            className={cn("h-1.5 flex-1 rounded-full", !color && (isDark ? "bg-white/10" : "bg-slate-100"))}
                            style={color ? { backgroundColor: color } : undefined}
                          />
                        ))}
                      </div>

                      <div className="flex flex-wrap items-center gap-1.5">
                        {p.techStack.slice(0, 3).map((t) => (
                          <span
                            key={t}
                            className={cn(
                              "rounded-md border px-1.5 py-0.5 text-[10px]",
                              isDark ? "border-white/10 text-slate-400" : "border-slate-200 text-slate-500"
                            )}
                          >
                            {t}
                          </span>
                        ))}
                        <span className={cn("ml-auto flex items-center gap-1 text-[11px]", isDark ? "text-slate-400" : "text-slate-500")}>
                          <Clock className="h-3 w-3" />
                          {formatRelative(p.updatedAt)}
                        </span>
                      </div>
                    </CardContent>
                  </Card>
                );
              })}
            </div>
          )}
        </div>

        {/* Quick actions */}
        <div className="mt-8 flex flex-wrap gap-2">
          <Button variant="outline" size="sm" onClick={() => navigate("/projects")}>
            <FolderKanban className="h-3.5 w-3.5" />
            All projects ({projects.length})
          </Button>
        </div>
    </div>
  );
}

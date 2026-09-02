import { useEffect, useMemo, useState } from "react";
import { useDocumentTitle } from "@/shared/hooks";
import { Link, useLocation, useNavigate } from "react-router-dom";
import { Plus, Search, FolderKanban, Clock, Trash2, ArrowRight, LayoutGrid, List } from "lucide-react";
import type { Project } from "@/types/project";
import { useSessionStore } from "@/store/session";
import { useUiStore } from "@/store/ui";
import { useProjectsList, useProjectMutations } from "../hooks";
import { getProjectsLoad, hydrateProjects, projectHomePath, useProjectsLoad } from "@/entities/project";
import { messageOf } from "@/lib/http";
import { ServerUnavailable } from "@/shared/ui/ServerUnavailable";
import { PageLoader } from "@/shared/ui/Spinner";
import { cn } from "@/shared/utils/cn";
import { ConfirmDialog } from "@/shared/ui/ConfirmDialog";
import { Badge, Button, Card, CardContent } from "@/shared/ui/primitives";
import { RunStoppedChip } from "@/shared/ui/RunStoppedChip";
import {
  SORT_ORDERS,
  STATUS_FILTERS,
  triage,
  type SortOrder,
  type StatusFilter,
} from "../model/triage";

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

function formatRelative(iso: string) {
  const diff = Date.now() - new Date(iso).getTime();
  const mins = Math.floor(diff / 60000);
  if (mins < 1) return "just now";
  if (mins < 60) return `${mins}m ago`;
  const hours = Math.floor(mins / 60);
  if (hours < 24) return `${hours}h ago`;
  const days = Math.floor(hours / 24);
  return `${days}d ago`;
}

export function Projects() {
  useDocumentTitle("Projects");
  // Statuses move while the reader is elsewhere, and the list was read once,
  // at sign-in. Read again on opening; a list that was read stays if this fails.
  useEffect(() => {
    if (getProjectsLoad().status === "loaded") void hydrateProjects().catch(() => undefined);
  }, []);
  const navigate = useNavigate();
  const theme = useUiStore((s) => s.theme);
  const addToast = useUiStore((s) => s.addToast);
  const setActiveProjectId = useSessionStore((s) => s.setActiveProjectId);
  const projects = useProjectsList();
  const load = useProjectsLoad();
  // Set by the project guard when a link named a project this account does not
  // have, so arriving here says why rather than looking like a wrong turn.
  const missing = (useLocation().state as { missing?: unknown } | null)?.missing;
  const { deleteProjectSync } = useProjectMutations();
  // Deleting asks first, for one project or for the ones selected. Holding the
  // projects rather than ids keeps their names for the messages.
  const [pendingDelete, setPendingDelete] = useState<Project[] | null>(null);
  const isDark = theme === "dark";
  const [query, setQuery] = useState("");
  const [status, setStatus] = useState<StatusFilter>("all");
  const [sort, setSort] = useState<SortOrder>("newest");
  const [view, setView] = useState<"grid" | "list">("grid");
  const [selected, setSelected] = useState<ReadonlySet<string>>(new Set());

  const filtered = useMemo(
    () => triage(projects, { query, status, sort }),
    [projects, query, status, sort],
  );
  // Only what is still listed counts as selected: a project deleted, or
  // filtered out, is not deleted again by a selection made before.
  const chosen = filtered.filter((p) => selected.has(p.id));

  const toggle = (id: string) =>
    setSelected((now) => {
      const next = new Set(now);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });

  // One at a time, each answered: a project with a run or a release going is
  // refused, and the others still go.
  const deleteAll = async (doomed: Project[]) => {
    const refused: string[] = [];
    let deleted = 0;
    for (const project of doomed) {
      try {
        await deleteProjectSync(project.id);
        deleted += 1;
      } catch (error) {
        refused.push(`${project.name}: ${messageOf(error)}`);
      }
    }
    setSelected(new Set());
    if (deleted > 0) {
      addToast({
        type: "info",
        title:
          doomed.length === 1
            ? "Project deleted"
            : `${deleted} ${deleted === 1 ? "project" : "projects"} deleted`,
        message: doomed.length === 1 ? doomed[0].name : undefined,
      });
    }
    if (refused.length > 0) {
      addToast({
        type: "error",
        title:
          doomed.length === 1
            ? `${doomed[0].name} was not deleted`
            : `${refused.length} ${refused.length === 1 ? "project was" : "projects were"} not deleted`,
        message: doomed.length === 1 ? refused[0].slice(doomed[0].name.length + 2) : refused.join(" "),
      });
    }
  };

  const remember = (p: Project) => setActiveProjectId(p.id);

  const field = cn(
    "h-10 rounded-xl border px-3 text-sm outline-none",
    isDark ? "border-white/10 bg-white/[0.03] text-slate-200" : "border-slate-200 bg-white text-slate-800",
  );
  const quiet = isDark ? "text-slate-400" : "text-slate-500";
  const toggleClass = (on: boolean) =>
    cn(
      "rounded-lg p-2",
      on
        ? isDark
          ? "bg-white/10 text-white"
          : "bg-slate-100 text-slate-900"
        : quiet,
    );
  const checkbox = "h-4 w-4 shrink-0 cursor-pointer accent-blue-600";

  return (
    <div className="w-full space-y-6 p-4 sm:p-6 md:p-8">
      <div>
        <div className="mb-1 flex items-center gap-2">
          <FolderKanban className={cn("h-5 w-5", isDark ? "text-blue-400" : "text-blue-600")} />
          <h2
            className={cn(
              "text-2xl font-semibold tracking-tight",
              isDark ? "text-white" : "text-slate-900",
            )}
          >
            Projects
          </h2>
        </div>
      </div>

      <div className="flex flex-col gap-3 sm:flex-row sm:flex-wrap sm:items-center">
        <div
          className={cn(
            "flex h-10 w-full flex-1 items-center gap-2 rounded-xl border px-3 sm:max-w-sm",
            isDark ? "border-white/10 bg-white/[0.03]" : "border-slate-200 bg-white",
          )}
        >
          <Search aria-hidden="true" className={cn("h-4 w-4", quiet)} />
          <input
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            aria-label="Search projects"
            placeholder="Search projects"
            className={cn(
              "w-full bg-transparent text-sm outline-none",
              isDark
                ? "text-slate-200 placeholder:text-slate-400"
                : "text-slate-800 placeholder:text-slate-500",
            )}
          />
        </div>
        <select
          aria-label="Show"
          value={status}
          onChange={(e) => setStatus(e.target.value as StatusFilter)}
          className={field}
        >
          {STATUS_FILTERS.map((option) => (
            <option key={option.value} value={option.value}>
              {option.label}
            </option>
          ))}
        </select>
        <select
          aria-label="Sort by"
          value={sort}
          onChange={(e) => setSort(e.target.value as SortOrder)}
          className={field}
        >
          {SORT_ORDERS.map((option) => (
            <option key={option.value} value={option.value}>
              {option.label}
            </option>
          ))}
        </select>
        <div
          className={cn(
            "flex rounded-xl border p-1",
            isDark ? "border-white/10 bg-white/[0.03]" : "border-slate-200 bg-white",
          )}
        >
          <button
            type="button"
            aria-label="Show as cards"
            aria-pressed={view === "grid"}
            onClick={() => setView("grid")}
            className={toggleClass(view === "grid")}
          >
            <LayoutGrid aria-hidden="true" className="h-4 w-4" />
          </button>
          <button
            type="button"
            aria-label="Show as a list"
            aria-pressed={view === "list"}
            onClick={() => setView("list")}
            className={toggleClass(view === "list")}
          >
            <List aria-hidden="true" className="h-4 w-4" />
          </button>
        </div>
      </div>

      {chosen.length > 0 && (
        <div
          role="region"
          aria-label="Selected projects"
          className={cn(
            "flex flex-wrap items-center gap-3 rounded-xl border px-3.5 py-2.5 text-sm",
            isDark ? "border-blue-500/30 bg-blue-500/10 text-slate-200" : "border-blue-200 bg-blue-50 text-slate-800",
          )}
        >
          <span className="font-medium">
            {chosen.length} {chosen.length === 1 ? "project" : "projects"} selected
          </span>
          <Button size="sm" variant="outline" onClick={() => setPendingDelete(chosen)}>
            <Trash2 aria-hidden="true" className="h-3.5 w-3.5" />
            Delete selected
          </Button>
          <Button size="sm" variant="outline" onClick={() => setSelected(new Set())}>
            Clear selection
          </Button>
        </div>
      )}

      {typeof missing === "string" && (
        <p
          role="status"
          className={cn(
            "mb-4 rounded-xl border px-3.5 py-2.5 text-sm",
            isDark ? "border-amber-500/30 bg-amber-500/10 text-amber-200" : "border-amber-200 bg-amber-50 text-amber-900",
          )}
        >
          That project no longer exists, or it belongs to another account.
        </p>
      )}

      {projects.length === 0 && load.status === "failed" ? (
        <ServerUnavailable
          title="Your projects could not be loaded"
          message={load.error ?? ""}
          onRetry={hydrateProjects}
        />
      ) : projects.length === 0 && load.status === "loading" ? (
        <PageLoader label="Loading your projects" />
      ) : filtered.length === 0 ? (
        <Card>
          <CardContent className="flex flex-col items-center justify-center px-6 py-20 text-center">
            <div
              className={cn(
                "mb-4 flex h-16 w-16 items-center justify-center rounded-2xl",
                isDark ? "bg-white/5" : "bg-slate-100",
              )}
            >
              <FolderKanban aria-hidden="true" className={cn("h-7 w-7", quiet)} />
            </div>
            <h3 className={cn("text-lg font-semibold", isDark ? "text-white" : "text-slate-900")}>
              {projects.length === 0 ? "No projects yet" : "No matching projects"}
            </h3>
            <p className={cn("mt-2 max-w-md text-sm", quiet)}>
              {projects.length === 0
                ? "Create your first project to start requirements analysis and the full AI-assisted SDLC pipeline."
                : "Try a different search, or show all projects."}
            </p>
            {projects.length === 0 && (
              <Button variant="primary" className="mt-6" onClick={() => navigate("/projects/new")}>
                <Plus className="h-4 w-4" />
                Create a new project
              </Button>
            )}
          </CardContent>
        </Card>
      ) : view === "grid" ? (
        <div className="grid grid-cols-1 gap-4 md:grid-cols-2 xl:grid-cols-3">
          {filtered.map((p) => {
            const st = statusBadge(p.status);
            return (
              // The title is the link, stretched over the card, so the whole
              // card opens the project and it is reachable by keyboard; it was
              // a div with a click handler. The checkbox and Delete sit above
              // the stretch and are always there, not only on hover.
              <Card
                key={p.id}
                className={cn(
                  "group relative overflow-hidden transition-all focus-within:ring-2 focus-within:ring-blue-500/40 hover:-translate-y-0.5",
                  isDark ? "hover:border-white/10" : "hover:border-slate-300 hover:shadow-md",
                )}
              >
                <div
                  className="h-28 w-full"
                  style={{ background: `linear-gradient(135deg, ${p.color}33, ${p.color}88)` }}
                >
                  <div className="flex h-full items-end justify-between p-4">
                    <div className="flex h-10 w-10 items-center justify-center rounded-xl bg-white/90 text-sm font-bold text-slate-800 shadow">
                      {p.name.charAt(0).toUpperCase()}
                    </div>
                    <input
                      type="checkbox"
                      aria-label={`Select ${p.name}`}
                      checked={selected.has(p.id)}
                      onChange={() => toggle(p.id)}
                      className={cn(checkbox, "relative z-10")}
                    />
                  </div>
                </div>
                <CardContent className="space-y-3 p-4">
                  <div className="flex items-start justify-between gap-2">
                    <div className="min-w-0">
                      <h3
                        className={cn(
                          "truncate text-[15px] font-semibold",
                          isDark ? "text-white" : "text-slate-900",
                        )}
                      >
                        <Link
                          to={projectHomePath(p)}
                          onClick={() => remember(p)}
                          className="outline-none after:absolute after:inset-0 after:content-['']"
                        >
                          {p.name}
                        </Link>
                      </h3>
                      <p className={cn("mt-1 line-clamp-2 text-xs", quiet)}>
                        {p.description || p.requirementText || "No description yet"}
                      </p>
                    </div>
                    <span className="flex shrink-0 flex-wrap justify-end gap-1">
                      <Badge variant={st.variant}>{st.label}</Badge>
                      {p.runStopped && <RunStoppedChip />}
                    </span>
                  </div>
                  <div className="h-1.5 overflow-hidden rounded-full bg-slate-100 dark:bg-white/10">
                    <div
                      className="h-full rounded-full bg-blue-500 transition-all"
                      style={{ width: `${p.progress}%` }}
                    />
                  </div>
                  {p.techStack.length > 0 && (
                    // The stack Code Generation chose, as Home shows it: every
                    // card went without one.
                    <div className="flex flex-wrap items-center gap-1.5" aria-label="Tech stack">
                      {p.techStack.slice(0, 3).map((layer) => (
                        <span
                          key={layer}
                          className={cn(
                            "rounded-md border px-1.5 py-0.5 text-[10px]",
                            isDark ? "border-white/10 text-slate-400" : "border-slate-200 text-slate-500",
                          )}
                        >
                          {layer}
                        </span>
                      ))}
                    </div>
                  )}
                  <div className="flex items-center justify-between">
                    <span className={cn("flex items-center gap-1 text-[11px]", quiet)}>
                      <Clock aria-hidden="true" className="h-3 w-3" />
                      {formatRelative(p.updatedAt)}
                    </span>
                    <div className="flex items-center gap-1">
                      <button
                        type="button"
                        onClick={() => setPendingDelete([p])}
                        aria-label={`Delete ${p.name}`}
                        title={`Delete ${p.name}`}
                        className={cn(
                          "relative z-10 rounded-lg p-1.5",
                          isDark ? "text-slate-400 hover:bg-white/5" : "text-slate-500 hover:bg-slate-100",
                        )}
                      >
                        <Trash2 aria-hidden="true" className="h-3.5 w-3.5" />
                      </button>
                      <span
                        aria-hidden="true"
                        className={cn(
                          "flex items-center gap-1 text-xs font-medium",
                          isDark ? "text-blue-300" : "text-blue-700",
                        )}
                      >
                        Open <ArrowRight className="h-3 w-3" />
                      </span>
                    </div>
                  </div>
                </CardContent>
              </Card>
            );
          })}
        </div>
      ) : (
        <Card>
          <CardContent className="space-y-1 p-2">
            {filtered.map((p) => {
              const st = statusBadge(p.status);
              return (
                <div
                  key={p.id}
                  className={cn(
                    "relative flex w-full items-center gap-4 rounded-xl px-3 py-3 transition-colors focus-within:ring-2 focus-within:ring-blue-500/40",
                    isDark ? "hover:bg-white/[0.04]" : "hover:bg-slate-50",
                  )}
                >
                  <input
                    type="checkbox"
                    aria-label={`Select ${p.name}`}
                    checked={selected.has(p.id)}
                    onChange={() => toggle(p.id)}
                    className={cn(checkbox, "relative z-10")}
                  />
                  <div
                    className="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl text-sm font-bold text-white"
                    style={{ backgroundColor: p.color }}
                  >
                    {p.name.charAt(0).toUpperCase()}
                  </div>
                  <div className="min-w-0 flex-1">
                    <div className="flex items-center gap-2">
                      <Link
                        to={projectHomePath(p)}
                        onClick={() => remember(p)}
                        className={cn(
                          "truncate text-sm font-semibold outline-none after:absolute after:inset-0 after:content-['']",
                          isDark ? "text-white" : "text-slate-900",
                        )}
                      >
                        {p.name}
                      </Link>
                      <Badge variant={st.variant}>{st.label}</Badge>
                      {p.runStopped && <RunStoppedChip />}
                    </div>
                    <p className={cn("truncate text-xs", quiet)}>
                      {p.description || p.requirementText || "No description yet"}
                    </p>
                  </div>
                  <span className={cn("hidden text-xs sm:inline", quiet)}>{p.progress}%</span>
                  <span className={cn("hidden text-xs sm:inline", quiet)}>{formatRelative(p.updatedAt)}</span>
                  <button
                    type="button"
                    onClick={() => setPendingDelete([p])}
                    aria-label={`Delete ${p.name}`}
                    title={`Delete ${p.name}`}
                    className={cn(
                      "relative z-10 rounded-lg p-1.5",
                      isDark ? "text-slate-400 hover:bg-white/5" : "text-slate-500 hover:bg-slate-100",
                    )}
                  >
                    <Trash2 aria-hidden="true" className="h-3.5 w-3.5" />
                  </button>
                </div>
              );
            })}
          </CardContent>
        </Card>
      )}

      {pendingDelete && (
        <ConfirmDialog
          title={pendingDelete.length === 1 ? "Delete this project?" : `Delete ${pendingDelete.length} projects?`}
          // What it removes and what it does not: it promised "everything
          // generated", and the GitHub repository and the cloud deployments
          // were left where they were.
          body={
            pendingDelete.length === 1
              ? `${pendingDelete[0].name}, its versions and its records here are deleted, and that cannot be undone. Its release on this machine goes with it. Its GitHub repository and any Vercel or Render deployments are not touched: delete those where they live if you no longer need them. The activity log keeps what was done.`
              : `${pendingDelete.map((one) => one.name).join(", ")}: their versions and their records here are deleted, and that cannot be undone. Their releases on this machine go with them. Their GitHub repositories and any Vercel or Render deployments are not touched: delete those where they live if you no longer need them. The activity log keeps what was done.`
          }
          confirmLabel={pendingDelete.length === 1 ? "Delete project" : `Delete ${pendingDelete.length} projects`}
          isDark={isDark}
          onCancel={() => setPendingDelete(null)}
          onConfirm={() => {
            const doomed = pendingDelete;
            setPendingDelete(null);
            // Said once the server has answered for each: a project with a run
            // or a release still going is refused, and says why.
            void deleteAll(doomed);
          }}
        />
      )}
    </div>
  );
}

export default Projects;

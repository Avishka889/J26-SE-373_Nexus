import { useNavigate, useLocation } from "react-router-dom";
import { Home, FolderKanban, X, Plus } from "lucide-react";
import { useSessionStore } from "@/store/session";
import { useUiStore } from "@/store/ui";
import { projectHomePath, useProjectsList } from "@/entities/project";
import { AccountMenu } from "@/app/layout/AccountMenu";
import { NexusWordmark } from "@/shared/ui/brand/NexusWordmark";
import { cn } from "@/shared/utils/cn";

const mainNav = [
  { id: "home", label: "Home", icon: Home, path: "/workspace" },
  { id: "projects", label: "Projects", icon: FolderKanban, path: "/projects" },
];

export function Sidebar({
  collapsed,
  mobileOpen,
  isMobileViewport,
  onNavigate,
}: {
  collapsed: boolean;
  mobileOpen: boolean;
  isMobileViewport: boolean;
  onNavigate?: () => void;
}) {
  const navigate = useNavigate();
  const location = useLocation();
  const theme = useUiStore((s) => s.theme);
  const setActiveProjectId = useSessionStore((s) => s.setActiveProjectId);
  const projects = useProjectsList();
  const isDark = theme === "dark";
  const recent = projects.slice(0, 5);

  /**
   * Which nav item, if any, the current route belongs to.
   *
   * Projects covers the list and the create screen, and stops there. Inside a
   * project the route belongs to that project, which has its own row below, and
   * lighting both said the reader was in two places at once.
   *
   * Creating a project still counts as Projects. That is where a new one goes,
   * and pointing at Home instead would name somewhere the reader is not.
   */
  const isActive = (path: string) => {
    if (path === "/workspace") return location.pathname === "/workspace";
    if (path === "/projects") {
      return (
        location.pathname === "/projects" ||
        location.pathname === "/projects/new"
      );
    }
    return (
      location.pathname === path || location.pathname.startsWith(path + "/")
    );
  };

  const go = (path: string) => {
    navigate(path);
    onNavigate?.();
  };

  return (
    <aside
      id="app-sidebar"
      // On a phone the drawer is a modal surface; from md up it is plain page
      // furniture, so the dialog semantics are dropped.
      role={isMobileViewport ? "dialog" : undefined}
      aria-modal={isMobileViewport ? true : undefined}
      aria-label={isMobileViewport ? "Main navigation" : undefined}
      // Off-screen but still in the DOM: without this, keyboard users tab into
      // invisible links behind the scrim.
      inert={isMobileViewport && !mobileOpen}
      className={cn(
        "flex h-full w-[min(280px,85vw)] shrink-0 flex-col border-r transition-transform duration-300 ease-in-out md:w-auto md:translate-x-0",
        collapsed ? "md:w-[68px]" : "md:w-[252px]",
        // Mobile: off-canvas drawer
        "fixed inset-y-0 left-0 z-50 md:static md:z-auto",
        mobileOpen ? "translate-x-0" : "-translate-x-full md:translate-x-0",
        isDark
          ? "border-white/[0.06] bg-[#0a1628]"
          : "border-slate-200/90 bg-white",
      )}
    >
      <div
        className={cn(
          "flex h-14 shrink-0 items-center gap-2 border-b px-3",
          collapsed ? "md:justify-center md:px-2" : "md:justify-start md:px-4",
          isDark ? "border-white/[0.06]" : "border-slate-200/80",
        )}
      >
        {/* Mobile drawer: logo mark + Nexus label */}
        <div className="flex min-w-0 flex-1 items-center gap-2.5 md:hidden">
          <NexusWordmark compact className="h-8 w-8 shrink-0" />
          <span
            className={cn(
              "truncate text-[15px] font-semibold tracking-tight",
              isDark ? "text-white" : "text-slate-900",
            )}
          >
            Nexus
          </span>
        </div>

        {/* Desktop: compact icon or full wordmark */}
        <NexusWordmark
          dark={isDark}
          compact={collapsed}
          className={cn(
            "hidden md:block",
            collapsed ? "h-9 w-9" : "h-10 w-[210px]",
          )}
        />

        <button
          type="button"
          className={cn(
            "flex h-8 w-8 shrink-0 items-center justify-center rounded-lg md:hidden",
            isDark
              ? "text-slate-400 hover:bg-white/10"
              : "text-slate-500 hover:bg-slate-100",
          )}
          aria-label="Close menu"
          onClick={onNavigate}
        >
          <X className="h-4 w-4" />
        </button>
      </div>

      <div className={cn("pb-3 pt-4", collapsed ? "px-2 max-md:px-3" : "px-3")}>
        <button
          onClick={() => go("/projects/new")}
          title="New project"
          className={cn(
            "flex items-center justify-center border-2 border-blue-600 bg-white font-semibold text-blue-600 transition-all",
            collapsed
              ? "mx-auto h-10 w-10 rounded-full max-md:mx-0 max-md:h-auto max-md:w-full max-md:gap-2 max-md:rounded-full max-md:px-3 max-md:py-2.5 max-md:text-[13px]"
              : "w-full gap-2 rounded-full px-3 py-2.5 text-[13px]",
          )}
        >
          <Plus className="h-4 w-4 shrink-0" />
          <span className={cn("truncate", collapsed && "md:hidden")}>
            New project
          </span>
        </button>
      </div>

      <nav
        className={cn(
          "flex-1 space-y-0.5 overflow-y-auto pt-2",
          collapsed ? "px-2 max-md:px-3" : "px-3",
        )}
      >
        {mainNav.map((item) => {
          const Icon = item.icon;
          const active = isActive(item.path);
          return (
            <button
              key={item.id}
              onClick={() => go(item.path)}
              title={item.label}
              className={cn(
                "flex w-full items-center rounded-xl py-2.5 text-[13px] font-medium transition-all md:py-2",
                collapsed
                  ? "justify-center px-0 max-md:justify-start max-md:gap-2.5 max-md:px-3"
                  : "gap-2.5 px-3",
                active
                  ? isDark
                    ? "bg-white/[0.08] text-white shadow-sm"
                    : "bg-blue-50 text-blue-900 shadow-sm"
                  : isDark
                    ? "text-slate-400 hover:bg-white/[0.04] hover:text-slate-200"
                    : "text-slate-500 hover:bg-blue-50/50 hover:text-slate-800",
              )}
            >
              <Icon
                className={cn(
                  "h-4 w-4 shrink-0",
                  active && (isDark ? "text-blue-400" : "text-blue-600"),
                )}
              />
              <span className={cn("truncate", collapsed && "md:hidden")}>
                {item.label}
              </span>
            </button>
          );
        })}

        {recent.length > 0 && (
          <div className={cn("pt-5", collapsed && "md:hidden")}>
            <p
              className={cn(
                "mb-2 px-3 text-[10px] font-semibold uppercase tracking-wider",
                isDark ? "text-slate-400" : "text-slate-500",
              )}
            >
              Recent projects
            </p>
            {recent.map((p) => {
              const active = location.pathname.includes(`/projects/${p.id}`);
              return (
                <button
                  key={p.id}
                  onClick={() => {
                    setActiveProjectId(p.id);
                    go(projectHomePath(p));
                  }}
                  className={cn(
                    "flex w-full items-center gap-2.5 rounded-xl px-3 py-2 text-[13px] transition-colors",
                    active
                      ? isDark
                        ? "bg-white/[0.06] text-white"
                        : "bg-blue-50 text-blue-900"
                      : isDark
                        ? "text-slate-400 hover:bg-white/[0.04]"
                        : "text-slate-500 hover:bg-blue-50/50",
                  )}
                >
                  <span
                    className="h-2 w-2 shrink-0 rounded-full"
                    style={{ backgroundColor: p.color }}
                  />
                  <span className="flex-1 truncate text-left">{p.name}</span>
                  <span
                    className={cn(
                      "text-[10px] tabular-nums",
                      // slate-600 in light: the open project's row is blue-50.
                      isDark ? "text-slate-400" : "text-slate-600",
                    )}
                  >
                    {p.progress}%
                  </span>
                </button>
              );
            })}
          </div>
        )}
      </nav>

      <div
        className={cn(
          "border-t p-2",
          isDark ? "border-white/[0.06]" : "border-slate-100",
        )}
      >
        <AccountMenu collapsed={collapsed} />
      </div>
    </aside>
  );
}

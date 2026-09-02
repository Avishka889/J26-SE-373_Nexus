import { type ComponentType, type KeyboardEvent } from "react";
import { useDocumentTitle } from "@/shared/hooks";
import { useSearchParams } from "react-router-dom";
import { User, GitBranch, Cloud, Brain, Server, Database } from "lucide-react";
import { useUiStore } from "@/store/ui";
import { cn } from "@/shared/utils/cn";
import { useSettingsActions, useSettingsLoad } from "@/entities/settings";
import {
  SettingsGate,
  ProfileTab,
  GitTab,
  VercelTab,
  RenderTab,
  DatabaseTab,
  AiTab,
} from "./components";

type SettingsTab = "profile" | "git" | "vercel" | "render" | "database" | "ai";

const tabs: {
  id: SettingsTab;
  label: string;
  description: string;
  icon: typeof User;
}[] = [
  {
    id: "profile",
    label: "Profile",
    description: "Your identity & workspace",
    icon: User,
  },
  {
    id: "git",
    label: "Git",
    description: "Source control provider",
    icon: GitBranch,
  },
  {
    id: "vercel",
    label: "Vercel",
    description: "Frontend deploy & previews",
    icon: Cloud,
  },
  {
    id: "render",
    label: "Render",
    description: "Backend services & APIs",
    icon: Server,
  },
  {
    id: "database",
    label: "Database",
    description: "MongoDB Atlas",
    icon: Database,
  },
  {
    id: "ai",
    label: "AI Model",
    description: "Generation preferences",
    icon: Brain,
  },
];

const tabContent: Record<SettingsTab, ComponentType> = {
  profile: ProfileTab,
  git: GitTab,
  vercel: VercelTab,
  render: RenderTab,
  database: DatabaseTab,
  ai: AiTab,
};

export function SettingsPage() {
  useDocumentTitle("Settings");
  const theme = useUiStore((s) => s.theme);
  const isDark = theme === "dark";
  // The open tab is in the address, so a reload or a shared link keeps it.
  const [params, setParams] = useSearchParams();
  const asked = params.get("tab");
  const tab: SettingsTab = tabs.some((item) => item.id === asked) ? (asked as SettingsTab) : "profile";
  const setTab = (next: SettingsTab) => setParams({ tab: next }, { replace: true });
  const ActiveTab = tabContent[tab];

  // The tabs pattern: one tab in the Tab order, the arrows move between them.
  const moveWithArrows = (event: KeyboardEvent<HTMLButtonElement>) => {
    const at = tabs.findIndex((item) => item.id === tab);
    const to =
      event.key === "ArrowRight" || event.key === "ArrowDown"
        ? (at + 1) % tabs.length
        : event.key === "ArrowLeft" || event.key === "ArrowUp"
          ? (at - 1 + tabs.length) % tabs.length
          : event.key === "Home"
            ? 0
            : event.key === "End"
              ? tabs.length - 1
              : -1;
    if (to < 0) return;
    event.preventDefault();
    setTab(tabs[to].id);
    document.getElementById(`settings-tab-${tabs[to].id}`)?.focus();
  };
  const load = useSettingsLoad();
  const { reloadSettings } = useSettingsActions();

  return (
    <div className="w-full px-4 py-8 md:px-8 md:py-10 lg:px-10">
      <header className="mb-8">
        <h1
          className={cn(
            "text-3xl font-semibold tracking-tight",
            isDark ? "text-white" : "text-slate-900",
          )}
        >
          Settings
        </h1>
      </header>

      <div className="flex flex-col gap-8 lg:flex-row lg:items-start lg:gap-10">
        <div
          role="tablist"
          aria-label="Settings sections"
          className={cn(
            "flex shrink-0 flex-row gap-1 overflow-x-auto rounded-2xl border p-1.5 lg:w-64 lg:flex-col",
            isDark
              ? "border-white/[0.08] bg-white/[0.03]"
              : "border-slate-200/80 bg-white/80 shadow-sm",
          )}
        >
          {tabs.map((item) => {
            const Icon = item.icon;
            const active = tab === item.id;
            return (
              <button
                key={item.id}
                type="button"
                role="tab"
                id={`settings-tab-${item.id}`}
                aria-selected={active}
                aria-controls="settings-panel"
                tabIndex={active ? 0 : -1}
                onKeyDown={moveWithArrows}
                onClick={() => setTab(item.id)}
                className={cn(
                  "flex min-w-[7.5rem] flex-1 items-center gap-2.5 rounded-xl px-3 py-2.5 text-left transition-all sm:min-w-[140px] sm:gap-3 sm:px-3.5 sm:py-3 lg:min-w-0 lg:flex-none",
                  active
                    ? isDark
                      ? "bg-blue-600/20 text-white ring-1 ring-blue-500/30"
                      : "bg-blue-50 text-blue-900 ring-1 ring-blue-200"
                    : isDark
                      ? "text-slate-400 hover:bg-white/[0.04] hover:text-slate-200"
                      : "text-slate-600 hover:bg-slate-50",
                )}
              >
                <Icon
                  className={cn(
                    "h-4 w-4 shrink-0",
                    active && (isDark ? "text-blue-400" : "text-blue-600"),
                  )}
                />
                <div className="min-w-0">
                  <p className="text-sm font-medium">{item.label}</p>
                  <p
                    className={cn(
                      "hidden truncate text-[11px] lg:block",
                      active
                        ? isDark
                          ? "text-slate-400"
                          : "text-blue-700"
                        : isDark
                          ? "text-slate-400"
                          : "text-slate-500",
                    )}
                  >
                    {item.description}
                  </p>
                </div>
              </button>
            );
          })}
        </div>

        <div
          role="tabpanel"
          id="settings-panel"
          aria-labelledby={`settings-tab-${tab}`}
          className="min-w-0 flex-1"
        >
          <SettingsGate load={load} onRetry={() => void reloadSettings()}>
            <ActiveTab />
          </SettingsGate>
        </div>
      </div>
    </div>
  );
}

export default SettingsPage;

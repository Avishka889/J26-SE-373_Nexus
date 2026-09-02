import { useEffect, useMemo, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import { Search, X } from "lucide-react";
import { useUiStore } from "@/store/ui";
import { projectHomePath, useProjectsList } from "@/entities/project";
import { useDialogFocus } from "@/shared/ui/useDialogFocus";
import { cn } from "@/shared/utils/cn";

const PAGES = [
  { id: "home", label: "Go to Home", path: "/workspace", category: "Navigation" },
  { id: "projects", label: "Projects", path: "/projects", category: "Navigation" },
  { id: "new", label: "Create new project", path: "/projects/new", category: "Action" },
  { id: "settings", label: "Settings", path: "/settings", category: "Navigation" },
];

/** How many projects show before anything is typed, and at most once something is. */
const RECENT = 8;
const MATCHES = 20;

/**
 * Jump to a page or a project with Ctrl or Cmd and K.
 *
 * It searched only the eight newest projects, because it cut the list before
 * matching, so the ninth project could not be found by name at all. Now every
 * project is matched and the matches are capped; with nothing typed it offers
 * the newest. A project opens at the phase its work is in.
 */
export function CommandPalette() {
  const commandPaletteOpen = useUiStore((s) => s.commandPaletteOpen);
  const setCommandPaletteOpen = useUiStore((s) => s.setCommandPaletteOpen);
  const theme = useUiStore((s) => s.theme);
  const projects = useProjectsList();
  const isDark = theme === "dark";
  const navigate = useNavigate();
  const [query, setQuery] = useState("");
  const [selected, setSelected] = useState(0);
  const dialog = useRef<HTMLDivElement | null>(null);
  useDialogFocus(dialog, () => setCommandPaletteOpen(false), commandPaletteOpen);

  const needle = query.trim().toLowerCase();
  const filtered = useMemo(() => {
    const matching = projects.filter((p) => p.name.toLowerCase().includes(needle));
    return [
      ...PAGES.filter((c) => c.label.toLowerCase().includes(needle)),
      ...(needle ? matching.slice(0, MATCHES) : matching.slice(0, RECENT)).map((p) => ({
        id: p.id,
        label: p.name,
        path: projectHomePath(p),
        category: "Projects",
      })),
    ];
  }, [projects, needle]);

  useEffect(() => {
    if (!commandPaletteOpen) return;
    const handler = (e: KeyboardEvent) => {
      if (e.key === "ArrowDown") {
        e.preventDefault();
        setSelected((s) => Math.min(s + 1, Math.max(filtered.length - 1, 0)));
      }
      if (e.key === "ArrowUp") {
        e.preventDefault();
        setSelected((s) => Math.max(s - 1, 0));
      }
      if (e.key === "Enter") {
        e.preventDefault();
        const cmd = filtered[selected];
        if (cmd) {
          navigate(cmd.path);
          setCommandPaletteOpen(false);
        }
      }
    };
    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
  }, [commandPaletteOpen, query, selected, navigate, setCommandPaletteOpen, filtered]);

  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key === "k") {
        e.preventDefault();
        setCommandPaletteOpen(!commandPaletteOpen);
      }
    };
    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
  }, [commandPaletteOpen, setCommandPaletteOpen]);

  if (!commandPaletteOpen) return null;

  return (
    <div
      className="fixed inset-0 z-[100] flex items-start justify-center bg-black/40 p-4 pt-[15vh] dark:bg-black/60"
      onClick={() => setCommandPaletteOpen(false)}
    >
      <div
        ref={dialog}
        role="dialog"
        aria-modal="true"
        aria-label="Search projects and pages"
        className={cn(
          "w-full max-w-xl rounded-2xl border shadow-2xl",
          isDark ? "border-white/10 bg-[#0f1d32]" : "border-slate-200 bg-white"
        )}
        onClick={(e) => e.stopPropagation()}
      >
        <div className={cn("flex items-center gap-2 border-b px-4", isDark ? "border-white/5" : "border-slate-100")}>
          <Search className={cn("h-4 w-4", isDark ? "text-slate-400" : "text-slate-500")} />
          <input
            data-autofocus
            value={query}
            onChange={(e) => {
              setQuery(e.target.value);
              setSelected(0);
            }}
            aria-label="Search projects and pages"
            placeholder="Search projects and pages..."
            className={cn(
              "h-12 flex-1 bg-transparent text-sm focus:outline-none",
              isDark ? "text-white placeholder:text-slate-400" : "text-slate-800 placeholder:text-slate-500"
            )}
          />
          <button type="button" aria-label="Close" onClick={() => setCommandPaletteOpen(false)}>
            <X aria-hidden="true" className={cn("h-4 w-4", isDark ? "text-slate-400" : "text-slate-500")} />
          </button>
        </div>
        <div className="max-h-80 overflow-auto p-2">
          {filtered.map((cmd, i) => (
            <button
              type="button"
              key={cmd.id}
              onMouseEnter={() => setSelected(i)}
              onClick={() => {
                navigate(cmd.path);
                setCommandPaletteOpen(false);
              }}
              className={cn(
                "flex w-full items-center gap-3 rounded-xl px-3 py-2.5 text-left text-sm transition-colors",
                selected === i
                  ? isDark
                    ? "bg-white/10 text-white"
                    : "bg-slate-100 text-slate-900"
                  : isDark
                  ? "text-slate-300"
                  : "text-slate-600"
              )}
            >
              <span className={cn("text-[10px] uppercase", isDark ? "text-slate-400" : "text-slate-600")}>
                {cmd.category}
              </span>
              <span>{cmd.label}</span>
            </button>
          ))}
          {filtered.length === 0 && (
            <p className={cn("px-3 py-4 text-center text-sm", isDark ? "text-slate-400" : "text-slate-500")}>
              No results found
            </p>
          )}
        </div>
      </div>
    </div>
  );
}

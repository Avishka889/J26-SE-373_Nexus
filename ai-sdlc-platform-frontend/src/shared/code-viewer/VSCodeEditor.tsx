import { useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { Check, Copy, X } from "lucide-react";
import { cn } from "@/shared/utils/cn";
import { useIsDark } from "@/shared/theme";
import { breadcrumbParts } from "@/shared/code-viewer/buildFileTree";
import { highlightCode, languageFromPath } from "@/shared/code-viewer/syntaxHighlight";
import { getFileIcon } from "@/shared/code-viewer/fileIcons";

export type EditorTab = {
  path: string;
  unsaved?: boolean;
};

const languageLabels: Record<string, string> = {
  tsx: "TypeScript JSX",
  typescript: "TypeScript",
  java: "Java",
  css: "CSS",
  json: "JSON",
  yaml: "YAML",
  dockerfile: "Dockerfile",
  plaintext: "Plain Text",
};

export function VSCodeEditor({
  tabs,
  activePath,
  contents,
  onSelectTab,
  onCloseTab,
  onDirty,
  highlight,
  showLanguage,
  copyable,
  statusBar,
}: {
  tabs: EditorTab[];
  activePath: string;
  contents: Record<string, string>;
  onSelectTab: (path: string) => void;
  onCloseTab: (path: string) => void;
  onDirty?: (path: string) => void;
  /** Open the file at a line - e.g. the assertion that failed. */
  highlight?: { path: string; line: number; label?: string };
  showLanguage?: boolean;
  copyable?: boolean;
  statusBar?: ReactNode;
}) {
  const isDark = useIsDark();
  const code = contents[activePath] ?? "";
  const language = languageFromPath(activePath);
  const highlighted = useMemo(() => highlightCode(code, language, isDark), [code, language, isDark]);
  const crumbs = breadcrumbParts(activePath);
  const { icon: Icon, color } = getFileIcon(activePath);
  const [copied, setCopied] = useState(false);

  const markedLine = highlight && highlight.path === activePath ? highlight.line : undefined;
  const bodyRef = useRef<HTMLDivElement | null>(null);
  const markedRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    if (!markedLine) return;
    const body = bodyRef.current;
    const row = markedRef.current;
    if (!body || !row) return;
    body.scrollTop = Math.max(0, row.offsetTop - body.clientHeight / 2);
  }, [markedLine, activePath]);

  const copy = async () => {
    try {
      await navigator.clipboard.writeText(code);
      setCopied(true);
      window.setTimeout(() => setCopied(false), 1600);
    } catch {
      setCopied(false);
    }
  };

  return (
    <div className={cn("flex h-full flex-col overflow-hidden rounded-xl border", isDark ? "border-white/10 bg-[#1e1e1e]" : "border-slate-200 bg-white")}>
      {/* Tab bar */}
      <div className={cn("flex border-b", isDark ? "border-white/10 bg-[#252526]" : "border-slate-200 bg-[#f3f3f3]")}>
        <div className="flex min-w-0 flex-1 overflow-x-auto">
          {tabs.map((tab) => {
            const active = tab.path === activePath;
            const TabIcon = getFileIcon(tab.path).icon;
            const tabColor = getFileIcon(tab.path).color;
            return (
              <div
                key={tab.path}
                className={cn(
                  "group flex max-w-[200px] shrink-0 items-center gap-1.5 border-r px-3 py-2 text-[12px]",
                  isDark ? "border-white/10" : "border-slate-200",
                  active
                    ? isDark
                      ? "bg-[#1e1e1e] text-slate-200"
                      : "bg-white text-slate-800"
                    : isDark
                    ? "bg-[#2d2d2d] text-slate-400 hover:bg-[#1e1e1e]"
                    : "bg-[#ececec] text-slate-500 hover:bg-white"
                )}
              >
                <button type="button" onClick={() => onSelectTab(tab.path)} className="flex min-w-0 flex-1 items-center gap-1.5">
                  <TabIcon className="h-3.5 w-3.5 shrink-0" style={{ color: tabColor }} />
                  <span className="truncate">{tab.path.split("/").pop()}</span>
                  {tab.unsaved && <span className="h-2 w-2 shrink-0 rounded-full bg-white" />}
                </button>
                <button
                  type="button"
                  onClick={() => onCloseTab(tab.path)}
                  aria-label={`Close ${tab.path.split("/").pop()}`}
                  className={cn("rounded p-0.5 opacity-0 transition-opacity group-hover:opacity-100", isDark ? "hover:bg-white/10" : "hover:bg-slate-200")}
                >
                  <X className="h-3 w-3" />
                </button>
              </div>
            );
          })}
        </div>
        {showLanguage && (
          <span
            className={cn(
              "hidden shrink-0 items-center px-3 font-mono text-[10px] uppercase tracking-[0.14em] sm:flex",
              isDark ? "text-slate-400" : "text-slate-600"
            )}
          >
            {languageLabels[language] ?? language}
          </span>
        )}
      </div>

      {/* Breadcrumb */}
      <div className={cn("flex items-center gap-1 border-b px-3 py-1.5 text-[11px]", isDark ? "border-white/10 bg-[#1e1e1e] text-slate-400" : "border-slate-100 bg-slate-50 text-slate-500")}>
        <Icon className="h-3 w-3 shrink-0" style={{ color }} />
        <div className="flex min-w-0 flex-1 items-center gap-1 overflow-hidden">
          {crumbs.map((part, i) => (
            <span key={i} className="flex shrink-0 items-center gap-1">
              {i > 0 && <span className="text-slate-600">›</span>}
              <span className={cn(i === crumbs.length - 1 && (isDark ? "text-slate-300" : "text-slate-700"))}>{part}</span>
            </span>
          ))}
        </div>
        {copyable && (
          <button
            type="button"
            onClick={copy}
            className={cn(
              "flex shrink-0 items-center gap-1 rounded px-1.5 py-0.5 transition-colors",
              isDark ? "hover:bg-white/[0.06] hover:text-slate-300" : "hover:bg-slate-200/70 hover:text-slate-700"
            )}
          >
            {copied ? <Check className="h-3 w-3" /> : <Copy className="h-3 w-3" />}
            {copied ? "Copied" : "Copy"}
          </button>
        )}
      </div>

      {/* Editor body */}
      {/* Focusable, so the code can be scrolled from the keyboard as well. */}
      <div
        ref={bodyRef}
        tabIndex={0}
        role="region"
        aria-label="File contents"
        className="relative min-h-0 flex-1 overflow-auto font-mono text-[13px] leading-[1.6] outline-none focus-visible:ring-2 focus-visible:ring-blue-500/40"
      >
        <div className="flex min-w-max">
          <div className={cn("sticky left-0 z-[1] select-none border-r py-3 pr-3 text-right", isDark ? "border-white/10 bg-[#1e1e1e] text-slate-400" : "border-slate-200 bg-slate-50 text-slate-500")}>
            {highlighted.map((_, i) => (
              <div
                key={i}
                className={cn(
                  "px-2",
                  i + 1 === markedLine && (isDark ? "bg-red-500/20 text-red-300" : "bg-red-50 text-red-600")
                )}
              >
                {i + 1}
              </div>
            ))}
          </div>
          <pre
            className={cn("min-w-0 flex-1 py-3", isDark ? "bg-[#1e1e1e]" : "bg-white")}
            onInput={() => onDirty?.(activePath)}
          >
            <code>
              {highlighted.map((line, i) => {
                const marked = i + 1 === markedLine;
                return (
                  <div
                    key={i}
                    ref={marked ? markedRef : undefined}
                    className={cn(
                      "border-l-2 pl-3.5",
                      marked
                        ? isDark
                          ? "border-red-400 bg-red-500/10"
                          : "border-red-500 bg-red-50/80"
                        : "border-transparent"
                    )}
                    dangerouslySetInnerHTML={{ __html: line || "&nbsp;" }}
                  />
                );
              })}
            </code>
          </pre>
        </div>
      </div>

      {(statusBar || markedLine) && (
        <div
          className={cn(
            "flex flex-wrap items-center gap-x-3 gap-y-1 border-t px-3 py-1.5 text-[11px]",
            isDark ? "border-white/10 bg-[#252526] text-slate-400" : "border-slate-200 bg-[#f3f3f3] text-slate-500"
          )}
        >
          {statusBar}
          {markedLine && (
            <span className={cn("font-mono", isDark ? "text-red-300" : "text-red-600")}>
              Line {markedLine}
              {highlight?.label ? ` · ${highlight.label}` : ""}
            </span>
          )}
          <span className="ml-auto font-mono uppercase tracking-[0.14em]">Read-only</span>
        </div>
      )}
    </div>
  );
}

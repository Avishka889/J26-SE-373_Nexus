import { useMemo, useState } from "react";
import { ChevronDown, ChevronRight, Folder, FolderOpen } from "lucide-react";
import { cn } from "@/shared/utils/cn";
import { buildFileTree, type FileEntry, type FileTreeNode } from "@/shared/code-viewer/buildFileTree";
import { getFileIcon } from "@/shared/code-viewer/fileIcons";
import { useIsDark } from "@/shared/theme";

function TypeBadge({ label, isDark }: { label: string; isDark: boolean }) {
  return (
    <span
      className={cn(
        "shrink-0 rounded px-1 py-0 text-[9px] uppercase tracking-wide",
        isDark ? "bg-white/[0.06] text-slate-300" : "bg-slate-200/80 text-slate-700"
      )}
    >
      {label}
    </span>
  );
}

function TreeNode({
  node,
  depth,
  selectedPath,
  onSelect,
  expanded,
  toggle,
  onTagClick,
  tagTitle,
}: {
  node: FileTreeNode;
  depth: number;
  selectedPath: string;
  onSelect: (path: string) => void;
  expanded: Set<string>;
  toggle: (path: string) => void;
  onTagClick?: (path: string, tag: string) => void;
  tagTitle?: (tag: string) => string;
}) {
  const isDark = useIsDark();
  const isFolder = node.kind === "folder";
  const isOpen = expanded.has(node.path);
  const isSelected = node.path === selectedPath;

  if (isFolder) {
    return (
      <div>
        <button
          type="button"
          onClick={() => toggle(node.path)}
          className={cn(
            "flex w-full items-center gap-1 rounded py-0.5 pr-2 text-left text-[12px]",
            isDark ? "text-slate-300 hover:bg-white/[0.06]" : "text-slate-700 hover:bg-slate-100"
          )}
          style={{ paddingLeft: `${depth * 12 + 4}px` }}
        >
          {isOpen ? <ChevronDown className="h-3.5 w-3.5 shrink-0 text-slate-500" /> : <ChevronRight className="h-3.5 w-3.5 shrink-0 text-slate-500" />}
          {isOpen ? <FolderOpen className="h-3.5 w-3.5 shrink-0 text-amber-400" /> : <Folder className="h-3.5 w-3.5 shrink-0 text-amber-400" />}
          <span className="truncate">{node.name}</span>
        </button>
        {isOpen &&
          node.children?.map((child) => (
            <TreeNode
              key={child.path}
              node={child}
              depth={depth + 1}
              selectedPath={selectedPath}
              onSelect={onSelect}
              expanded={expanded}
              toggle={toggle}
              onTagClick={onTagClick}
              tagTitle={tagTitle}
            />
          ))}
      </div>
    );
  }

  const { icon: Icon, color } = getFileIcon(node.path, node.file?.type);
  const tags = node.file?.tags ?? [];

  return (
    <div
      className={cn(
        "group flex w-full items-center gap-1.5 rounded pr-2 text-[12px]",
        isSelected
          ? isDark
            ? "bg-blue-500/15 text-blue-200"
            : "bg-blue-50 text-blue-800"
          : isDark
          ? "text-slate-400 hover:bg-white/[0.04]"
          : "text-slate-600 hover:bg-slate-50"
      )}
    >
      <button
        type="button"
        onClick={() => onSelect(node.path)}
        className="flex min-w-0 flex-1 items-center gap-1.5 py-0.5 text-left"
        style={{ paddingLeft: `${depth * 12 + 20}px` }}
      >
        <Icon className="h-3.5 w-3.5 shrink-0" style={{ color }} />
        <span className="min-w-0 flex-1 truncate">{node.name}</span>
      </button>
      {node.file?.type && <TypeBadge label={node.file.type} isDark={isDark} />}
      {tags.map((tag) =>
        onTagClick ? (
          <button
            key={tag}
            type="button"
            onClick={() => onTagClick(node.path, tag)}
            title={tagTitle?.(tag)}
            className={cn(
              "shrink-0 rounded px-1 py-0 text-[9px] uppercase tracking-wide transition-colors",
              isDark
                ? "bg-emerald-500/15 text-emerald-300 hover:bg-emerald-500/25"
                : "bg-emerald-50 text-emerald-700 hover:bg-emerald-100"
            )}
          >
            {tag}
          </button>
        ) : (
          <TypeBadge key={tag} label={tag} isDark={isDark} />
        )
      )}
    </div>
  );
}

export function VSCodeFileTree({
  files,
  selectedPath,
  onSelect,
  title,
  collapseChains,
  onTagClick,
  tagTitle,
  footer,
}: {
  files: FileEntry[];
  selectedPath: string;
  onSelect: (path: string) => void;
  title: string;
  collapseChains?: boolean;
  onTagClick?: (path: string, tag: string) => void;
  tagTitle?: (tag: string) => string;
  footer?: React.ReactNode;
}) {
  const isDark = useIsDark();
  const tree = useMemo(() => buildFileTree(files, { collapseChains }), [files, collapseChains]);
  const [expanded, setExpanded] = useState<Set<string>>(() => {
    const paths = new Set<string>();
    files.forEach((f) => {
      f.path.split("/").slice(0, -1).reduce((acc, part) => {
        const p = acc ? `${acc}/${part}` : part;
        paths.add(p);
        return p;
      }, "");
    });
    return paths;
  });

  const toggle = (path: string) => {
    setExpanded((prev) => {
      const next = new Set(prev);
      if (next.has(path)) next.delete(path);
      else next.add(path);
      return next;
    });
  };

  return (
    <div className={cn("flex h-full flex-col overflow-hidden rounded-xl border", isDark ? "border-white/10 bg-[#1e1e1e]" : "border-slate-200 bg-[#f3f3f3]")}>
      <div className={cn("border-b px-3 py-2 text-[11px] font-semibold uppercase tracking-wide", isDark ? "border-white/10 text-slate-400" : "border-slate-200 text-slate-600")}>
        {title}
      </div>
      <div className="flex-1 overflow-y-auto py-1 font-mono">
        {tree.map((node) => (
          <TreeNode
            key={node.path}
            node={node}
            depth={0}
            selectedPath={selectedPath}
            onSelect={onSelect}
            expanded={expanded}
            toggle={toggle}
            onTagClick={onTagClick}
            tagTitle={tagTitle}
          />
        ))}
      </div>
      {footer && (
        <div className={cn("border-t px-3 py-2", isDark ? "border-white/10" : "border-slate-200")}>{footer}</div>
      )}
    </div>
  );
}

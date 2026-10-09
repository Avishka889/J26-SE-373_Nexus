import { useState, useCallback } from "react";
import type { EditorTab } from "@/shared/code-viewer";

/** Shared editor-tab state for code-viewer consumers (code-gen, deployment, testing). */
export function useEditorTabs(defaultPath: string) {
  const [tabs, setTabs] = useState<EditorTab[]>([{ path: defaultPath }]);
  const [activePath, setActivePath] = useState(defaultPath);

  const openFile = useCallback((path: string) => {
    setTabs((prev) => (prev.some((t) => t.path === path) ? prev : [...prev, { path }]));
    setActivePath(path);
  }, []);

  const closeTab = useCallback(
    (path: string) => {
      setTabs((prev) => {
        const next = prev.filter((t) => t.path !== path);
        if (next.length === 0) return prev;
        if (activePath === path) setActivePath(next[next.length - 1].path);
        return next;
      });
    },
    [activePath],
  );

  return { tabs, activePath, openFile, closeTab, setActivePath };
}

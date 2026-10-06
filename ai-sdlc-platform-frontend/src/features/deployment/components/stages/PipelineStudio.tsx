import { useMemo } from "react";
import { useQueries } from "@tanstack/react-query";
import { VSCodeEditor } from "@/shared/code-viewer/VSCodeEditor";
import { VSCodeFileTree } from "@/shared/code-viewer/VSCodeFileTree";
import type { FileEntry } from "@/shared/code-viewer/buildFileTree";
import { useEditorTabs } from "@/shared/hooks";
import { deploymentKeys } from "@/lib/query";
import { deploymentApi } from "../../api";
import type { DeploySnapshot } from "../../api/types";
import { Spinner } from "@/shared/ui/Spinner";

type PipelineFile = NonNullable<DeploySnapshot["pipeline"]>["files"][number];

/**
 * The generated deployment files, in the explorer and editor Code Generation
 * uses, so a reader who has opened a file in one phase has opened one here.
 *
 * Each row is tagged with what the file is for; the template it came from, its
 * size and the secrets it names are on the editor's status bar, because a
 * template id beside every name squeezed the names themselves out of a third
 * of the width. Bodies arrive one at a time: the snapshot carries none,
 * because it is polled while a run is in flight, so the editor asks for a file
 * when a tab opens it and keeps the answer, a file at a version never changing.
 */
export function PipelineStudio({
  projectId,
  version,
  files,
}: {
  projectId: string;
  version: number;
  files: PipelineFile[];
}) {
  const entries: FileEntry[] = useMemo(
    () =>
      files.map((file) => ({
        path: file.path,
        type: file.path.split(".").pop() ?? "txt",
        tags: [file.purpose],
      })),
    [files],
  );

  const defaultPath = entries[0]?.path ?? "";
  const { tabs, activePath, openFile, closeTab, setActivePath } = useEditorTabs(defaultPath);

  // Derived rather than synced, as Code Generation's studio does: a new version
  // without the open file must not leave the editor on a path it did not write.
  const known = useMemo(() => new Set(entries.map((entry) => entry.path)), [entries]);
  const openTabs = tabs.filter((tab) => known.has(tab.path));
  const effectiveTabs = openTabs.length > 0 ? openTabs : defaultPath ? [{ path: defaultPath }] : [];
  const effectivePath = known.has(activePath) ? activePath : defaultPath;

  const bodies = useQueries({
    queries: effectiveTabs.map((tab) => ({
      queryKey: deploymentKeys.file(projectId, tab.path, version),
      queryFn: () => deploymentApi.getFile(projectId, tab.path, version),
      enabled: Boolean(projectId && tab.path),
      staleTime: Infinity,
    })),
  });

  const contents: Record<string, string> = {};
  let loading = false;
  effectiveTabs.forEach((tab, index) => {
    const query = bodies[index];
    if (query?.data) contents[tab.path] = query.data.content;
    else if (query?.isError)
      contents[tab.path] =
        `# ${tab.path}\n# This file could not be read. It may belong to an earlier\n` +
        "# deploy version than the one on screen.\n";
    else loading = true;
  });

  const open = files.find((file) => file.path === effectivePath);

  return (
    <div className="grid h-auto grid-cols-1 gap-4 md:h-[560px] md:grid-cols-3">
      <VSCodeFileTree
        title="Explorer"
        files={entries}
        selectedPath={effectivePath}
        onSelect={openFile}
        tagTitle={() => "What this file is for"}
      />
      <div className="min-h-[320px] md:col-span-2 md:min-h-0">
        <VSCodeEditor
          tabs={effectiveTabs}
          activePath={effectivePath}
          contents={contents}
          onSelectTab={setActivePath}
          onCloseTab={closeTab}
          showLanguage
          copyable
          statusBar={
            loading ? (
              <span className="flex items-center gap-1.5">
                <Spinner size="xs" decorative />
                reading the file
              </span>
            ) : open ? (
              <span className="truncate">
                from {open.templateId} · {open.bytes} bytes
                {open.secretsReferenced.length > 0
                  ? ` · names ${open.secretsReferenced.length} secret${open.secretsReferenced.length === 1 ? "" : "s"}, never their values`
                  : ""}
                {open.valid ? " · passed its validators" : " · failed a validator"}
              </span>
            ) : null
          }
        />
      </div>
    </div>
  );
}

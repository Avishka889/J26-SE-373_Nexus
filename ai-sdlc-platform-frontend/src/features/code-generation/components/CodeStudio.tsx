import { useMemo } from "react";
import { useQueries } from "@tanstack/react-query";
import { VSCodeEditor } from "@/shared/code-viewer/VSCodeEditor";
import { VSCodeFileTree } from "@/shared/code-viewer/VSCodeFileTree";
import type { FileEntry } from "@/shared/code-viewer/buildFileTree";
import { Note, Panel } from "@/shared/ui/phase";
import { StageSection } from "@/shared/ui/stage";
import { useEditorTabs } from "@/shared/hooks";
import { codeKeys } from "@/lib/query";
import { codeApi } from "../api";
import type { CodeSnapshot } from "../api/types";
import { fileTags } from "../model/manifest";
import { Spinner } from "@/shared/ui/Spinner";

/**
 * What a code stage wrote, in an explorer and an editor.
 *
 * The same viewer Testing and Deployment use, so a reader who has opened a
 * file in one phase has opened one in all of them. It reads the real manifest
 * rather than a checked in blob of demo source: the tree is the files the run
 * actually wrote, and each row's badges say which generator authored it and
 * from which contract arm, which is the fact a manifest exists to carry.
 *
 * Bodies arrive one at a time. The snapshot deliberately carries none, because
 * it is polled every 1.2 seconds while a run is in flight and a run writes
 * tens of files, so the editor asks for a file when a tab opens it and keeps
 * the answer for good: a file at a version never changes, because the run that
 * wrote it has finished.
 */
export function CodeStudio({
  projectId,
  snapshot,
  sectionId,
  stages,
  emptyLine,
}: {
  projectId: string;
  snapshot: CodeSnapshot;
  sectionId: string;
  /** The manifest stages this studio is about. */
  stages: string[];
  emptyLine: string;
}) {
  const manifest = snapshot.repository?.manifest;
  const wanted = stages.join(",");
  const rows = useMemo(
    () => (manifest ?? []).filter((row) => wanted.split(",").includes(row.stage)),
    [manifest, wanted],
  );

  const files: FileEntry[] = useMemo(
    () =>
      rows.map((row) => ({
        path: row.path,
        type: row.path.split(".").pop() ?? "txt",
        // The manifest's own facts, on the row: who wrote it, and from which
        // arm. A model filled file reading `rule` would be the one thing this
        // record must never say.
        tags: fileTags(row),
      })),
    [rows],
  );

  const defaultPath = files[0]?.path ?? "";
  const { tabs, activePath, openFile, closeTab, setActivePath } = useEditorTabs(defaultPath);

  /**
   * Follow the manifest when a regeneration changes it, by deriving rather
   * than by syncing.
   *
   * `useEditorTabs` seeds from the first render's default and keeps its own
   * state after that, so a version that no longer contains the open file would
   * otherwise leave the editor pointed at a path the run did not write. An
   * effect that corrected it would be state chasing state; computing what is
   * actually openable each render cannot fall behind.
   */
  const known = useMemo(() => new Set(files.map((file) => file.path)), [files]);
  const openTabs = tabs.filter((tab) => known.has(tab.path));
  const effectiveTabs = openTabs.length > 0 ? openTabs : defaultPath ? [{ path: defaultPath }] : [];
  const effectivePath = known.has(activePath) ? activePath : defaultPath;

  // One query per open tab, so a body is fetched once and only when a reader
  // has actually opened it.
  const bodies = useQueries({
    queries: effectiveTabs.map((tab) => ({
      queryKey: codeKeys.file(projectId, tab.path, snapshot.codeVersion),
      queryFn: () => codeApi.getFile(projectId, tab.path, snapshot.codeVersion),
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
        `// ${tab.path}\n// This file could not be read. It may belong to an earlier\n` +
        "// code version than the one on screen.\n";
    else loading = true;
  });

  const openRow = rows.find((row) => row.path === effectivePath);

  return (
    <StageSection id={sectionId}>
      <Panel
        label={`Files (${rows.length})`}
        title="Every generated file, with who wrote it and what it implements."
      >
        {rows.length === 0 ? (
          <Note>{emptyLine}</Note>
        ) : (
          <>
            <div className="grid h-auto grid-cols-1 gap-4 md:h-[560px] md:grid-cols-3">
              <VSCodeFileTree
                title="Explorer"
                files={files}
                selectedPath={effectivePath}
                onSelect={openFile}
                tagTitle={(tag) =>
                  tag === "model"
                    ? "A model wrote this body, and it was accepted only after passing the post checks"
                    : tag === "rule"
                      ? "The deterministic generator wrote this from the contract"
                      : tag === "static"
                        ? "A checked in template, identical in every generated project"
                        : `Generated from the ${tag}`
                }
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
                    ) : openRow ? (
                      <span className="truncate">
                        {openRow.summary}
                        {openRow.implements.length > 0
                          ? ` · implements ${openRow.implements.join(", ")}`
                          : ""}
                      </span>
                    ) : null
                  }
                />
              </div>
            </div>
            <Note className="mt-3">
              Code version {snapshot.codeVersion}. A file is fetched when you open it and
              never re-fetched: the run that wrote it has finished, so it cannot change.
            </Note>
          </>
        )}
      </Panel>
    </StageSection>
  );
}

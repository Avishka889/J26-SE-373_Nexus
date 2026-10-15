import { useEffect, useRef } from "react";
import { Modal } from "@/shared/ui/Modal";
import { useCodeFile } from "../hooks/useCode";
import { PageLoader } from "@/shared/ui/Spinner";

/**
 * One generated file, fetched when it is opened and not before.
 *
 * File bodies are deliberately absent from the snapshot, which is polled every
 * 1.2 seconds while a run is in flight. A reader who wants to read one asks
 * for that one, and a file at a version never changes, so the answer is cached
 * for good.
 */
export function FileViewer({
  projectId,
  path,
  version,
  line,
  onClose,
}: {
  projectId: string;
  path: string;
  version: number;
  /** The line a finding cited: marked, and scrolled to once the file is read. */
  line?: number;
  onClose: () => void;
}) {
  const query = useCodeFile(projectId, path, version);
  const cited = useRef<HTMLSpanElement | null>(null);
  const content = query.data?.content;
  useEffect(() => {
    if (content !== undefined) cited.current?.scrollIntoView?.({ block: "center" });
  }, [content]);

  return (
    <Modal title={path} subtitle={`code version ${version}`} onClose={onClose}>
      {query.isPending ? (
        <PageLoader label="Reading the file" className="py-12" />
      ) : query.isError ? (
        <p className="tp-den p-4">
          This file could not be read. It may belong to an earlier code version than the one
          on screen.
        </p>
      ) : (
        <pre className="min-h-full overflow-auto p-4 font-mono text-[11.5px] leading-[1.65] text-[color:var(--tp-ink)]">
          {line
            ? (content ?? "").split("\n").map((text, index) => (
                <span
                  key={index}
                  ref={index + 1 === line ? cited : undefined}
                  data-cited-line={index + 1 === line ? "" : undefined}
                  className={index + 1 === line ? "-mx-4 block bg-amber-500/15 px-4" : "block"}
                >
                  {text || " "}
                </span>
              ))
            : content}
        </pre>
      )}
    </Modal>
  );
}

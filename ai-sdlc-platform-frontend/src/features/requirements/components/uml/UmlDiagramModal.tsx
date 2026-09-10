import {
  useCallback,
  useEffect,
  useRef,
  useState,
  type ReactNode,
  type Ref,
} from "react";
import { Download, Minus, Plus, RotateCcw, X } from "lucide-react";
import { useDialogFocus } from "@/shared/ui/useDialogFocus";
import { cn } from "@/shared/utils/cn";
import { surface } from "@/shared/ui/surface";
import { MermaidDiagram } from "@/shared/viz";
import { diagramFileName, downloadSvg } from "@/shared/viz/download";
import type { UmlDiagram } from "../../api/types";

/**
 * One diagram, given the room to be read.
 *
 * A modal rather than the Fullscreen API: the wireframe player is already a
 * modal so the gesture is the one readers know here, fullscreen needs a user
 * gesture and behaves differently per browser, and it takes away the chrome a
 * reader uses to get back.
 *
 * Zoom is a transform on a wrapper rather than a re-render. Mermaid draws
 * vectors, so scaling costs nothing and stays sharp at any size.
 */

const ZOOM_STEP = 0.25;
const MIN_ZOOM = 0.5;
const MAX_ZOOM = 3;

function IconButton({
  children,
  label,
  isDark,
  disabled,
  onClick,
  buttonRef,
}: {
  children: ReactNode;
  label: string;
  isDark: boolean;
  disabled?: boolean;
  onClick: () => void;
  buttonRef?: Ref<HTMLButtonElement>;
}) {
  return (
    <button
      ref={buttonRef}
      type="button"
      aria-label={label}
      title={label}
      disabled={disabled}
      onClick={onClick}
      className={cn(
        "flex h-8 w-8 items-center justify-center rounded-lg border transition-colors disabled:opacity-40",
        isDark
          ? "border-white/10 text-slate-300 hover:bg-white/[0.06]"
          : "border-slate-200 text-slate-600 hover:bg-slate-100",
      )}
    >
      {children}
    </button>
  );
}

function TextButton({
  children,
  isDark,
  busy,
  onClick,
}: {
  children: ReactNode;
  isDark: boolean;
  busy: boolean;
  onClick: () => void;
}) {
  return (
    <button
      type="button"
      disabled={busy}
      onClick={onClick}
      className={cn(
        "flex h-8 items-center gap-1.5 rounded-lg border px-2.5 text-[12px] font-medium transition-colors disabled:opacity-50",
        isDark
          ? "border-white/10 text-slate-300 hover:bg-white/[0.06]"
          : "border-slate-200 text-slate-600 hover:bg-slate-100",
      )}
    >
      {children}
    </button>
  );
}

export function UmlDiagramModal({
  diagram,
  source,
  projectName,
  version,
  isDark,
  onClose,
}: {
  diagram: UmlDiagram;
  source: string;
  /** Named in the download, so a folder of exports says which project. */
  projectName: string;
  /** The requirements version this diagram came from, likewise. */
  version: number;
  isDark: boolean;
  onClose: () => void;
}) {
  const [zoom, setZoom] = useState(1);
  const [saving, setSaving] = useState(false);
  const [failed, setFailed] = useState<string | null>(null);
  const holder = useRef<HTMLDivElement>(null);
  const closeRef = useRef<HTMLButtonElement>(null);

  const dialog = useRef<HTMLDivElement>(null);
  useDialogFocus(dialog, onClose);
  // Declared after the hook, so the opener it records is the page's, not this.
  useEffect(() => closeRef.current?.focus(), []);

  // The page's own surface, so a saved copy is legible on a reader's document
  // rather than dark text on nothing.
  const background = isDark ? "#0b1524" : "#ffffff";

  const download = useCallback(() => {
    const svg = holder.current?.querySelector("svg");
    if (!svg) {
      setFailed("The diagram has not finished drawing yet.");
      return;
    }
    setFailed(null);
    setSaving(true);
    try {
      downloadSvg(
        svg,
        diagramFileName(projectName, diagram.kind, version, "svg"),
        background,
      );
    } catch {
      // Saving is not worth interrupting a reader for, but silence would leave
      // them waiting for a file that is never coming.
      setFailed("That diagram could not be saved.");
    } finally {
      setSaving(false);
    }
  }, [background, diagram.kind, projectName, version]);

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4">
      <button
        type="button"
        className="absolute inset-0 bg-black/50 backdrop-blur-sm"
        aria-label="Close the diagram"
        onClick={onClose}
      />
      <div
        ref={dialog}
        role="dialog"
        aria-modal="true"
        aria-label={diagram.title}
        className={cn(
          // A fixed frame, not one that fits each diagram. Four views of the
          // same design are meant to be compared, and a window that resizes
          // between them moves the drawing under the reader's eye every time
          // they switch. The diagram scrolls and zooms inside a constant field.
          "relative z-10 flex h-[85vh] w-full max-w-[1100px] flex-col overflow-hidden rounded-2xl shadow-2xl",
          surface.modal(isDark),
        )}
      >
        <div
          className={cn(
            "flex flex-wrap items-center justify-between gap-3 border-b px-5 py-3.5",
            isDark ? "border-white/[0.06]" : "border-slate-100",
          )}
        >
          <div className="min-w-0">
            <h2 className="truncate text-[15px] font-semibold text-[color:var(--tp-ink)]">
              {diagram.title}
            </h2>
            {diagram.description && (
              <p className="truncate text-[12px] text-[color:var(--tp-ink-2)]">
                {diagram.description}
              </p>
            )}
          </div>

          <div className="flex items-center gap-1.5">
            <IconButton
              label="Zoom out"
              isDark={isDark}
              disabled={zoom <= MIN_ZOOM}
              onClick={() => setZoom((z) => Math.max(MIN_ZOOM, z - ZOOM_STEP))}
            >
              <Minus className="h-4 w-4" />
            </IconButton>
            <span className="w-12 text-center text-[12px] tabular-nums text-[color:var(--tp-ink-2)]">
              {Math.round(zoom * 100)}%
            </span>
            <IconButton
              label="Zoom in"
              isDark={isDark}
              disabled={zoom >= MAX_ZOOM}
              onClick={() => setZoom((z) => Math.min(MAX_ZOOM, z + ZOOM_STEP))}
            >
              <Plus className="h-4 w-4" />
            </IconButton>
            <IconButton
              label="Reset zoom"
              isDark={isDark}
              onClick={() => setZoom(1)}
            >
              <RotateCcw className="h-4 w-4" />
            </IconButton>

            <span
              className={cn(
                "mx-1 h-5 w-px",
                isDark ? "bg-white/10" : "bg-slate-200",
              )}
            />

            {/* SVG only. A raster of a vector diagram is soft the moment
                anyone zooms it, and offering the worse format invites picking
                it. Everything a reader will paste this into takes SVG. */}
            <TextButton isDark={isDark} busy={saving} onClick={download}>
              <Download className="h-3.5 w-3.5" /> Download SVG
            </TextButton>

            <IconButton
              label="Close"
              isDark={isDark}
              onClick={onClose}
              buttonRef={closeRef}
            >
              <X className="h-4 w-4" />
            </IconButton>
          </div>
        </div>

        {failed && (
          <p className="border-b border-amber-500/30 bg-amber-500/5 px-5 py-2 text-[12px] text-[color:var(--tp-ink)]">
            {failed}
          </p>
        )}

        <div className="flex-1 overflow-auto p-5">
          {/* The wrapper is full width so the diagram fills the room it was
              opened to get. The transform scales the drawing alone: the border
              and background belong to the modal, and scaling those made the zoom
              look like it was resizing a card rather than the diagram. */}
          <div
            ref={holder}
            style={{ transform: `scale(${zoom})`, transformOrigin: "top left" }}
          >
            <MermaidDiagram
              chart={source}
              id={`${diagram.id}-modal-${source.length}`}
              isDark={isDark}
              minHeight={0}
              fit
              className="!border-0 !bg-transparent"
            />
          </div>
        </div>
      </div>
    </div>
  );
}

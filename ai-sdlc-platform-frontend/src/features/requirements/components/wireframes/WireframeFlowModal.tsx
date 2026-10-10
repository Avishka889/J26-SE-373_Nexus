import { useRef, useState } from "react";
import { useDialogFocus } from "@/shared/ui/useDialogFocus";
import { ChevronRight, MessageSquare, RotateCcw, Send, X } from "lucide-react";
import { cn } from "@/shared/utils/cn";
import { Button } from "@/shared/ui/primitives";
import { surface } from "@/shared/ui";
import { Note } from "@/shared/ui/phase";
import type { WireframeFlow } from "../../api/types";
import { ScreenPreview } from "./ScreenPreview";

/**
 * The clickable prototype.
 *
 * It carries no Approve action. Approving the design is a phase decision and
 * happens once, at Design Review; what belongs here is the item level action,
 * asking for this one flow to be redrawn.
 */
export function WireframeFlowModal({
  flow,
  projectName,
  isOpen,
  isDark,
  onClose,
  onRequestRefinement,
  initialScreenId,
}: {
  flow: WireframeFlow;
  /** The screen to open at, when a link named one; the first otherwise. */
  initialScreenId?: string | null;
  /** Read from the project, never from a brand baked into the fixture. */
  projectName: string;
  isOpen: boolean;
  isDark: boolean;
  onClose: () => void;
  onRequestRefinement: (note: string) => void | Promise<unknown>;
}) {
  const [screenIndex, setScreenIndex] = useState(() =>
    Math.max(0, flow.screens.findIndex((one) => one.id === initialScreenId)),
  );
  const [showLinks, setShowLinks] = useState(false);
  const [composing, setComposing] = useState(false);
  const [note, setNote] = useState("");

  const dialog = useRef<HTMLDivElement>(null);
  useDialogFocus(dialog, onClose, isOpen);

  if (!isOpen) return null;

  const screen = flow.screens[Math.min(screenIndex, flow.screens.length - 1)];
  const crumbs = [projectName, ...screen.crumbs];

  const navigate = (targetId: string) => {
    const next = flow.screens.findIndex((s) => s.id === targetId);
    if (next >= 0) setScreenIndex(next);
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4">
      <button
        type="button"
        className="absolute inset-0 bg-black/50 backdrop-blur-sm"
        aria-label="Close the prototype"
        onClick={onClose}
      />
      <div
        ref={dialog}
        role="dialog"
        aria-modal="true"
        aria-label={`${flow.name} prototype`}
        className={cn(
          "relative z-10 flex max-h-[90vh] w-full max-w-[820px] flex-col overflow-hidden rounded-2xl shadow-2xl",
          surface.modal(isDark),
        )}
      >
        <div
          className={cn(
            "flex flex-wrap items-start justify-between gap-3 border-b px-5 py-4",
            isDark ? "border-white/[0.06]" : "border-slate-100",
          )}
        >
          <div className="min-w-0">
            <h3 className={cn("text-sm font-semibold", isDark ? "text-white" : "text-slate-900")}>
              Click through the flow
            </h3>
            <p className="tp-den mt-0.5">
              Anything outlined is clickable, exactly like the real app will be.
            </p>
          </div>
          <div className="flex items-center gap-2">
            <label className="tp-den flex items-center gap-1.5">
              <input
                type="checkbox"
                checked={showLinks}
                onChange={(e) => setShowLinks(e.target.checked)}
                className="h-3.5 w-3.5 accent-blue-600"
              />
              Show links
            </label>
            <Button size="sm" variant="ghost" aria-label="Close" onClick={onClose}>
              <X className="h-4 w-4" />
            </Button>
          </div>
        </div>

        <div className="min-h-0 flex-1 overflow-auto px-5 py-4">
          <nav aria-label="Breadcrumb" className="mb-3 flex flex-wrap items-center gap-1">
            <span className="h-1.5 w-1.5 rounded-full bg-blue-500" />
            {crumbs.map((crumb, i) => (
              <span key={`${crumb}-${i}`} className="flex items-center gap-1">
                <span
                  className={cn(
                    "rounded px-1.5 py-0.5 text-[11px]",
                    i === crumbs.length - 1
                      ? isDark
                        ? "bg-white/10 text-slate-200"
                        : "bg-slate-100 text-slate-700"
                      : "text-[color:var(--tp-muted)]",
                  )}
                >
                  {crumb}
                </span>
                {i < crumbs.length - 1 && <ChevronRight className="h-3 w-3 text-[color:var(--tp-muted)]" />}
              </span>
            ))}
          </nav>

          <div className="min-h-[320px]">
            <ScreenPreview screen={screen} isDark={isDark} showLinks={showLinks} onNavigate={navigate} />
          </div>

          {composing && (
            <div className="mt-4 rounded-xl border border-[color:var(--tp-line)] px-3.5 py-3">
              <label className="tp-label block" htmlFor="refine-note">
                What should change about the {flow.name} flow
              </label>
              <textarea
                id="refine-note"
                autoFocus
                rows={3}
                value={note}
                onChange={(e) => setNote(e.target.value)}
                placeholder="The fee should be visible before the customer confirms."
                className="mt-2 w-full resize-none rounded-xl border border-[color:var(--tp-line)] bg-transparent px-3 py-2 text-[13px] outline-none focus:border-blue-500/50"
              />
              <Note className="mt-1.5">
                Sending this is a change to the design: it opens a new version, and the design is
                generated again with your note (once the review is decided, if one is waiting).
                Approving the whole design happens once, at Design Review.
              </Note>
              <div className="mt-2 flex flex-wrap gap-2">
                <Button
                  size="sm"
                  variant="primary"
                  disabled={!note.trim()}
                  onClick={async () => {
                    try {
                      await onRequestRefinement(note.trim());
                      setNote("");
                      setComposing(false);
                      onClose();
                    } catch {
                      // Reported where it failed; the note stays to send again.
                    }
                  }}
                >
                  <Send className="h-3.5 w-3.5" />
                  Send
                </Button>
                <Button size="sm" variant="outline" onClick={() => setComposing(false)}>
                  Cancel
                </Button>
              </div>
            </div>
          )}
        </div>

        <div
          className={cn(
            "flex flex-wrap items-center gap-3 border-t px-5 py-3",
            isDark ? "border-white/[0.06]" : "border-slate-100",
          )}
        >
          <div className="flex items-center gap-1.5">
            {flow.screens.map((s, i) => (
              <button
                key={s.id}
                type="button"
                aria-label={`Go to ${s.name}`}
                aria-current={i === screenIndex}
                onClick={() => setScreenIndex(i)}
                className={cn(
                  "h-2 w-2 rounded-full transition-colors",
                  i === screenIndex ? "bg-blue-500" : isDark ? "bg-white/20" : "bg-slate-300",
                )}
              />
            ))}
            <span className="tp-den ml-2">{screen.name}</span>
          </div>

          <div className="ml-auto flex flex-wrap gap-2">
            {screenIndex > 0 && (
              <Button size="sm" variant="ghost" onClick={() => setScreenIndex(0)}>
                <RotateCcw className="h-3.5 w-3.5" />
                Restart flow
              </Button>
            )}
            <Button size="sm" variant="outline" onClick={() => setComposing((v) => !v)}>
              <MessageSquare className="h-3.5 w-3.5" />
              Request refinements
            </Button>
          </div>
        </div>
      </div>
    </div>
  );
}

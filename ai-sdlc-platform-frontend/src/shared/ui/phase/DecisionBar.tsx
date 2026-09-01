import { useState } from "react";
import { ArrowRight, MessageSquare } from "lucide-react";
import { cn } from "@/shared/utils/cn";
import { Button } from "@/shared/ui/primitives";
import { useIsDark } from "@/shared/theme";

/**
 * The phase decision. It appears when a phase is waiting on a human, spans the
 * bottom, and never blocks navigation: every step stays reachable behind it.
 * Built from the app's surfaces and buttons; the only motion is the amber dot
 * that marks "waiting on you".
 *
 * Every phase has exactly one of these, and it is the only place a phase level
 * decision can be made. Item level decisions belong inside their stage.
 *
 * What failed or is still open comes first, and approving over any of it asks
 * for a note saying why, which goes on the record with the approval. Approving
 * was one click whatever had failed: a code version was approved with its
 * typecheck failing, and the line that said so was cut off on a phone.
 */
export function DecisionBar({
  headline,
  detail,
  concerns = [],
  approveLabel,
  requestLabel = "Request changes",
  notePrompt,
  notePlaceholder,
  onApprove,
  onRequestChanges,
  approveDisabled = false,
  approveDisabledReason,
  changesDisabledReason,
  busy = false,
}: {
  headline: string;
  /** The line under the headline: where the phase stands, or what was decided. */
  detail: string;
  /**
   * What failed or is still open, each in a few words ("the build did not pass").
   * Shown before anything else; approving over any of them needs a note.
   */
  concerns?: string[];
  approveLabel: string;
  requestLabel?: string;
  notePrompt: string;
  notePlaceholder: string;
  /** The note is the reviewer's reason for approving over the concerns, when there are any. */
  onApprove: (note?: string) => void | Promise<unknown>;
  /** A returned promise keeps the note open until it is accepted, and open if it fails. */
  onRequestChanges: (note: string) => void | Promise<unknown>;
  /** The gate is not armed yet. The bar stays put and says why. */
  approveDisabled?: boolean;
  approveDisabledReason?: string;
  /**
   * Why requesting changes would not help, for example a review the phase has
   * moved past: the changes would regenerate from what is no longer current.
   * The button is off and the bar says what to do instead.
   */
  changesDisabledReason?: string;
  /** A decision is already on its way; neither action may be sent twice. */
  busy?: boolean;
}) {
  const isDark = useIsDark();
  // Which note is open: one asking for changes, or one saying why to approve anyway.
  const [composing, setComposing] = useState<"changes" | "approve" | null>(null);
  const [note, setNote] = useState("");
  const [sending, setSending] = useState(false);
  const outstanding = concerns.length > 0;

  const open = (which: "changes" | "approve") => {
    setComposing((now) => (now === which ? null : which));
    setNote("");
  };

  // The note is the reviewer's reasoning: it closes only once the decision is
  // accepted, and a refusal leaves it open with its text.
  const sendNote = async () => {
    const text = note.trim();
    if (!text || sending || composing === null) return;
    setSending(true);
    try {
      await (composing === "approve" ? onApprove(text) : onRequestChanges(text));
      setNote("");
      setComposing(null);
    } catch {
      // Reported where it failed; the note stays open.
    } finally {
      setSending(false);
    }
  };

  return (
    <div
      className={cn(
        "sticky bottom-0 z-20 -mx-4 border-t backdrop-blur-xl sm:-mx-6 md:-mx-8",
        isDark
          ? "border-white/[0.06] bg-[#0a1628]/95"
          : "border-slate-200/80 bg-white/95",
      )}
    >
      {composing && (
        <div
          className={cn(
            "border-b px-4 py-3 sm:px-6 md:px-8",
            isDark ? "border-white/[0.06]" : "border-slate-100",
          )}
        >
          <label className="tp-label block" htmlFor="phase-note">
            {composing === "approve" ? "Why approve with this outstanding" : notePrompt}
          </label>
          <textarea
            id="phase-note"
            autoFocus
            rows={2}
            value={note}
            onChange={(e) => setNote(e.target.value)}
            placeholder={
              composing === "approve"
                ? "Say why this is right to approve as it is. The note is kept with the approval."
                : notePlaceholder
            }
            className={cn(
              "mt-2 w-full resize-none rounded-xl border bg-transparent px-3 py-2 text-[13px] outline-none focus:border-blue-500/50",
              isDark
                ? "border-white/10 text-slate-100 placeholder:text-slate-400"
                : "border-slate-200 text-slate-800 placeholder:text-slate-500",
            )}
          />
          <div className="mt-2 flex flex-wrap gap-2">
            <Button
              size="sm"
              variant="primary"
              disabled={!note.trim()}
              busy={busy || sending}
              onClick={() => void sendNote()}
            >
              {composing === "approve" ? "Approve anyway" : "Send the note"}
            </Button>
            <Button
              size="sm"
              variant="outline"
              onClick={() => setComposing(null)}
            >
              Cancel
            </Button>
          </div>
        </div>
      )}

      <div className="safe-pb flex flex-col gap-3 px-4 py-3 sm:px-6 md:px-8 lg:flex-row lg:flex-wrap lg:items-center">
        <span className="relative mt-1 flex h-2 w-2 shrink-0 lg:mt-0">
          <span className="tp-pending-edge absolute inline-flex h-full w-full rounded-full bg-amber-400" />
          <span className="relative inline-flex h-2 w-2 rounded-full bg-amber-500" />
        </span>

        <div className="min-w-0 flex-1 lg:basis-64">
          <p
            className={cn(
              "text-[13px] font-semibold",
              isDark ? "text-white" : "text-slate-900",
            )}
          >
            {headline}
          </p>
          {outstanding && (
            <p
              className={cn(
                "mt-0.5 break-words text-[12.5px] font-medium",
                isDark ? "text-amber-300" : "text-amber-700",
              )}
            >
              Outstanding: {concerns.join(" · ")}
            </p>
          )}
          <p className="tp-den mt-0.5 break-words">
            {approveDisabled && approveDisabledReason
              ? approveDisabledReason
              : detail}
          </p>
          {changesDisabledReason && (
            <p className="tp-den mt-0.5 break-words">{changesDisabledReason}</p>
          )}
        </div>

        <div className="flex shrink-0 gap-2">
          <Button
            variant="outline"
            className={cn(
              "flex-1 lg:flex-none",
              composing === "changes" && (isDark ? "bg-white/5" : "bg-slate-100"),
            )}
            disabled={Boolean(changesDisabledReason)}
            title={changesDisabledReason}
            onClick={() => open("changes")}
          >
            <MessageSquare className="h-3.5 w-3.5" />
            {requestLabel}
          </Button>
          <Button
            variant="primary"
            className="flex-1 lg:flex-none"
            disabled={approveDisabled}
            busy={busy}
            title={approveDisabled ? approveDisabledReason : undefined}
            onClick={() =>
              outstanding
                ? open("approve")
                : // Reported where it failed, as a refused note is.
                  void Promise.resolve(onApprove()).catch(() => undefined)
            }
          >
            {approveLabel}
            <ArrowRight className="h-3.5 w-3.5" />
          </Button>
        </div>
      </div>
    </div>
  );
}

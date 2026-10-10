import { cn } from "@/shared/utils/cn";
import type { FlowScreen, ScreenBlock } from "../../api/types";
import { groupBlocks } from "../../model/blocks";

/**
 * A screen drawn from its blocks rather than from a hardcoded ladder of screen
 * ids. That is what lets any screen render anywhere, including scaled down into
 * a card thumbnail, without a special case per screen.
 */
export function ScreenPreview({
  screen,
  isDark,
  showLinks = false,
  onNavigate,
  interactive = true,
}: {
  screen: FlowScreen;
  isDark: boolean;
  showLinks?: boolean;
  onNavigate?: (targetId: string) => void;
  /** Thumbnails render the same markup with nothing clickable. */
  interactive?: boolean;
}) {
  const linkById = Object.fromEntries(screen.links.map((l) => [l.id, l]));

  const go = (linkId: string | null) => {
    if (!interactive || !linkId) return;
    const link = linkById[linkId];
    if (link && onNavigate) onNavigate(link.targetId);
  };

  return (
    <div
      className={cn(
        "flex h-full flex-col gap-2.5 rounded-xl border p-4",
        isDark ? "border-white/10 bg-[#0b1524]" : "border-slate-200 bg-white",
      )}
    >
      <div className="flex items-center gap-1.5">
        <span className="h-2 w-2 rounded-full bg-red-400/70" />
        <span className="h-2 w-2 rounded-full bg-amber-400/70" />
        <span className="h-2 w-2 rounded-full bg-emerald-400/70" />
        <span className={cn("ml-2 text-[11px] font-medium", isDark ? "text-slate-400" : "text-slate-500")}>
          {screen.name}
        </span>
      </div>

      <div className="flex flex-1 flex-col gap-2">
        {groupBlocks(screen.blocks).map((group) =>
          group.kind === "keys" ? (
            <div key={group.blocks[0].id} className="grid grid-cols-4 gap-1.5">
              {group.blocks.map((key) => (
                <button
                  key={key.id}
                  type="button"
                  disabled={!interactive || !key.linkId}
                  onClick={() => go(key.linkId)}
                  className={cn(
                    "rounded-lg border px-2 py-1.5 text-[11px] font-semibold",
                    isDark ? "border-white/10 text-slate-200" : "border-slate-200 text-slate-700",
                    showLinks && key.linkId && "ring-2 ring-blue-400",
                  )}
                >
                  {key.label}
                </button>
              ))}
            </div>
          ) : (
            <Block
              key={group.block.id}
              block={group.block}
              isDark={isDark}
              showLinks={showLinks}
              clickable={interactive && Boolean(group.block.linkId)}
              onActivate={() => go(group.block.linkId)}
            />
          ),
        )}
      </div>

      <div className="flex flex-wrap items-center gap-2 pt-1">
        {screen.links
          .filter((link) => link.variant === "primary" || link.variant === "secondary")
          .map((link) => (
            <button
              key={link.id}
              type="button"
              disabled={!interactive}
              onClick={() => onNavigate?.(link.targetId)}
              className={cn(
                "rounded-lg px-3 py-1.5 text-[11px] font-semibold transition-colors",
                link.variant === "primary"
                  ? "bg-blue-600 text-white"
                  : isDark
                    ? "border border-white/15 text-slate-300"
                    : "border border-slate-200 text-slate-600",
                showLinks && "ring-2 ring-blue-400",
                interactive && "hover:opacity-90",
              )}
            >
              {link.label}
            </button>
          ))}
        {screen.links
          .filter((link) => link.variant === "text")
          .map((link) => (
            <button
              key={link.id}
              type="button"
              disabled={!interactive}
              onClick={() => onNavigate?.(link.targetId)}
              className={cn(
                "text-[11px] underline",
                isDark ? "text-slate-400" : "text-slate-500",
                showLinks && "ring-2 ring-blue-400",
              )}
            >
              {link.label}
            </button>
          ))}
      </div>
    </div>
  );
}

function Block({
  block,
  isDark,
  showLinks,
  clickable,
  onActivate,
}: {
  block: ScreenBlock;
  isDark: boolean;
  showLinks: boolean;
  clickable: boolean;
  onActivate: () => void;
}) {
  const toneText =
    block.tone === "positive"
      ? "text-emerald-500"
      : block.tone === "muted"
        ? isDark
          ? "text-slate-400"
          : "text-slate-500"
        : isDark
          ? "text-slate-200"
          : "text-slate-700";

  if (block.kind === "banner") {
    return (
      <div
        className={cn(
          "rounded-lg px-3 py-2 text-[11px] font-semibold",
          block.tone === "positive"
            ? "bg-emerald-500/10 text-emerald-500"
            : isDark
              ? "bg-white/[0.04] text-slate-300"
              : "bg-slate-100 text-slate-600",
        )}
      >
        {block.label}
      </div>
    );
  }

  if (block.kind === "display") {
    // A read-out, drawn large and to the right, as a calculator's is.
    return (
      <div className={cn("rounded-lg px-3 py-2 text-right", isDark ? "bg-white/[0.04]" : "bg-slate-50")}>
        <p className={cn("text-[10px] uppercase tracking-wide", isDark ? "text-slate-400" : "text-slate-500")}>
          {block.label}
        </p>
        <p className={cn("font-mono text-xl font-semibold tabular-nums", isDark ? "text-white" : "text-slate-900")}>
          {block.value || "0"}
        </p>
      </div>
    );
  }

  if (block.kind === "summary") {
    return (
      <div className={cn("rounded-lg px-3 py-2.5", isDark ? "bg-white/[0.04]" : "bg-slate-50")}>
        <p className={cn("text-[10px] uppercase tracking-wide", isDark ? "text-slate-400" : "text-slate-500")}>
          {block.label}
        </p>
        <p className={cn("text-lg font-semibold tabular-nums", isDark ? "text-white" : "text-slate-900")}>
          {block.value}
        </p>
      </div>
    );
  }

  if (block.kind === "text") {
    return <p className={cn("text-[11px] leading-relaxed", toneText)}>{block.label}</p>;
  }

  if (block.kind === "field") {
    return (
      <div>
        <p className={cn("text-[10px]", isDark ? "text-slate-400" : "text-slate-500")}>{block.label}</p>
        <div
          className={cn(
            "mt-0.5 rounded-lg border px-2.5 py-1.5 text-[11px]",
            isDark ? "border-white/10 text-slate-300" : "border-slate-200 text-slate-600",
          )}
        >
          {block.value}
        </div>
      </div>
    );
  }

  // A row and a list item are both a tappable line, which is what they are.
  if (clickable) {
    return (
      <button
        type="button"
        onClick={onActivate}
        className={cn(
          "flex w-full items-center justify-between rounded-lg border px-2.5 py-1.5 text-left hover:border-blue-400/60",
          isDark ? "border-white/10" : "border-slate-200",
          showLinks && "ring-2 ring-blue-400",
        )}
      >
        <span className={cn("text-[11px]", isDark ? "text-slate-300" : "text-slate-600")}>
          {block.label}
        </span>
        {block.value && <span className={cn("text-[11px] tabular-nums", toneText)}>{block.value}</span>}
      </button>
    );
  }

  return (
    <div
      className={cn(
        "flex w-full items-center justify-between rounded-lg border px-2.5 py-1.5",
        isDark ? "border-white/10" : "border-slate-200",
      )}
    >
      <span className={cn("text-[11px]", isDark ? "text-slate-300" : "text-slate-600")}>
        {block.label}
      </span>
      {block.value && <span className={cn("text-[11px] tabular-nums", toneText)}>{block.value}</span>}
    </div>
  );
}

/**
 * The same screen at card size. It is the real screen scaled, not a drawing of
 * one, so a card can never show something the player does not.
 */
export function ScreenMiniature({
  screen,
  isDark,
  className,
}: {
  screen: FlowScreen;
  isDark: boolean;
  className?: string;
}) {
  // A fixed design width scaled down, centred, so the preview keeps one shape
  // whatever width the card happens to be.
  const width = 360;
  const scale = 0.62;

  return (
    <div
      className={cn("relative flex justify-center overflow-hidden", className)}
      aria-hidden="true"
    >
      <div
        className="pointer-events-none origin-top"
        style={{ width, height: 330, transform: `scale(${scale})`, marginBottom: 330 * (scale - 1) }}
      >
        <ScreenPreview screen={screen} isDark={isDark} interactive={false} />
      </div>
    </div>
  );
}

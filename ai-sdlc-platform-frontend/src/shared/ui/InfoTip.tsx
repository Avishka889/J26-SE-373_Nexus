import { useId, useLayoutEffect, useRef, useState } from "react";
import { useIsDark } from "@/shared/theme";
import { cn } from "@/shared/utils/cn";

/**
 * Supplemental information behind a small info icon, shown above it in a dark
 * bubble while the icon is hovered or focused, as `docs/tooltip_image.png`
 * draws it.
 *
 * The icon is a real button, so a keyboard reaches it and a screen reader names
 * it, and the bubble is its description. A caller passes `id` to make the same
 * text the description of the field it explains (`aria-describedby`), which is
 * how `Field` uses it. The bubble stays while the pointer moves onto it, and
 * Escape closes it without moving the pointer or the focus (WCAG 1.4.13). It
 * opens towards the right of the icon rather than centred on it, because the
 * icon sits beside a label at the left of a form, where a centred bubble would
 * run off a phone's screen; and it measures itself as it opens, sliding left
 * when it would cross the right edge (its arrow still under the icon) and
 * opening below when there is no room above.
 */
export function InfoTip({
  text,
  label,
  id,
}: {
  text: string;
  /** The icon's name, for a screen reader: "About Cluster". */
  label: string;
  /** The bubble's id, for a field to point its `aria-describedby` at. */
  id?: string;
}) {
  const own = useId();
  const tipId = id ?? own;
  const [open, setOpen] = useState(false);
  const [place, setPlace] = useState({ shift: 0, below: false });
  const bubble = useRef<HTMLSpanElement>(null);
  const isDark = useIsDark();

  // Measured where it first lands, 8px left of the icon and above it.
  useLayoutEffect(() => {
    const box = bubble.current?.getBoundingClientRect();
    if (!open || !box) {
      setPlace({ shift: 0, below: false });
      return;
    }
    const over = box.right - (window.innerWidth - 8);
    setPlace({
      shift: over > 0 ? Math.max(0, Math.min(over, box.left - 8)) : 0,
      below: box.top < 8,
    });
  }, [open, text]);

  return (
    <span
      className="relative inline-flex"
      onMouseEnter={() => setOpen(true)}
      onMouseLeave={() => setOpen(false)}
    >
      <button
        type="button"
        aria-label={label}
        aria-describedby={tipId}
        onFocus={() => setOpen(true)}
        onBlur={() => setOpen(false)}
        onClick={() => setOpen(true)}
        onKeyDown={(event) => {
          if (event.key === "Escape") setOpen(false);
        }}
        className={cn(
          "inline-flex h-4 w-4 shrink-0 items-center justify-center rounded-full outline-none focus-visible:ring-2 focus-visible:ring-blue-400 focus-visible:ring-offset-1",
          isDark
            ? "bg-blue-500 text-white focus-visible:ring-offset-slate-900"
            : "bg-blue-900 text-white focus-visible:ring-offset-white",
        )}
      >
        <svg
          viewBox="0 0 16 16"
          aria-hidden="true"
          className="h-2.5 w-2.5"
          fill="currentColor"
        >
          <circle cx="8" cy="3" r="1.75" />
          <rect x="6.5" y="6" width="3" height="9" rx="1.25" />
        </svg>
      </button>
      <span
        ref={bubble}
        role="tooltip"
        id={tipId}
        style={{ transform: `translateX(${-8 - place.shift}px)` }}
        className={cn(
          "absolute left-0 z-30 w-max max-w-[min(18rem,calc(100vw_-_2rem))] rounded-lg px-3 py-2 text-left text-xs font-normal leading-relaxed shadow-lg transition-opacity duration-150",
          place.below ? "top-full mt-2" : "bottom-full mb-2",
          isDark
            ? "bg-slate-700 text-white ring-1 ring-white/10"
            : "bg-neutral-800 text-white",
          open ? "visible opacity-100" : "invisible opacity-0",
        )}
      >
        {text}
        {/* The arrow, at the icon's centre: the bubble starts 8px left of the
            icon, so the centre is 16px in, plus however far it slid left. */}
        <span
          aria-hidden="true"
          style={{ left: 10 + place.shift }}
          className={cn(
            "absolute border-[6px] border-transparent",
            place.below
              ? isDark
                ? "bottom-full border-b-slate-700"
                : "bottom-full border-b-neutral-800"
              : isDark
                ? "top-full border-t-slate-700"
                : "top-full border-t-neutral-800",
          )}
        />
      </span>
    </span>
  );
}

import { useId, useState, type ReactNode } from "react";
import { ChevronDown } from "lucide-react";
import { cn } from "@/shared/utils/cn";

/**
 * A list a reader opens when they need it.
 *
 * The summary line always shows and says what is inside; the list itself starts
 * closed. For the places one item can carry hundreds of rows, such as a
 * package's release notes, where the page around the list is what is being
 * read. What goes inside keeps its own styles: this adds a way in, not a look.
 */
export function Expandable({
  summary,
  children,
  defaultOpen = false,
  className,
}: {
  summary: ReactNode;
  children: ReactNode;
  defaultOpen?: boolean;
  className?: string;
}) {
  const [open, setOpen] = useState(defaultOpen);
  const regionId = useId();
  return (
    <div className={className}>
      <button
        type="button"
        aria-expanded={open}
        aria-controls={regionId}
        onClick={() => setOpen((was) => !was)}
        className="flex w-full items-center gap-2 rounded-xl border border-[color:var(--tp-line)] px-3 py-2 text-left text-[12.5px] text-[color:var(--tp-ink)] transition-colors hover:bg-[color:var(--tp-surface-2)]"
      >
        <ChevronDown
          aria-hidden
          className={cn(
            "h-4 w-4 shrink-0 text-[color:var(--tp-muted)] transition-transform",
            open && "rotate-180",
          )}
        />
        <span className="min-w-0 flex-1 break-words">{summary}</span>
        <span aria-hidden className="tp-den shrink-0">
          {open ? "Hide" : "Show"}
        </span>
      </button>
      {open && (
        <div id={regionId} className="mt-2">
          {children}
        </div>
      )}
    </div>
  );
}

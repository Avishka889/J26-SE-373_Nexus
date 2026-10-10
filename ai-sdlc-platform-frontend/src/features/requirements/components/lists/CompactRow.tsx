import type { ReactNode } from "react";
import { ChevronDown } from "lucide-react";
import { cn } from "@/shared/utils/cn";

/**
 * One line by default, the whole record when opened.
 *
 * Twenty requirements as full height cards is five screens of scrolling before
 * the approver has seen the list they are meant to approve. Compactness, not
 * concealment: every row is present, nothing is paginated away, and the count
 * line above says exactly how many are showing out of how many exist.
 *
 * The whole row is the toggle, so there is no hunting for a chevron, and the
 * chevron itself is the affordance that says it opens.
 */
export function CompactRow({
  open,
  onToggle,
  lead,
  tags,
  trailing,
  children,
  focused = false,
  rowId,
}: {
  open: boolean;
  onToggle: () => void;
  /** The id and the one line of text: what the row is, at a glance. */
  lead: ReactNode;
  /** Type, priority, attribute. Small, and on the same line at desk width. */
  tags?: ReactNode;
  /** Confidence or a count. Right aligned, and never the reason to open. */
  trailing?: ReactNode;
  /** Everything the row was hiding. */
  children: ReactNode;
  focused?: boolean;
  rowId?: string;
}) {
  return (
    <li
      data-row-id={rowId}
      className={cn(
        "border-t border-[color:var(--tp-line)] first:border-t-0",
        focused && "bg-blue-500/[0.07] ring-2 ring-inset ring-blue-500/40",
      )}
    >
      <button
        type="button"
        onClick={onToggle}
        aria-expanded={open}
        className="flex w-full items-center gap-3 px-4 py-2.5 text-left transition-colors hover:bg-[color:var(--tp-surface-2)]"
      >
        <span className="min-w-0 flex-1">{lead}</span>
        {tags && <span className="hidden shrink-0 items-center gap-1.5 md:flex">{tags}</span>}
        {trailing && <span className="shrink-0">{trailing}</span>}
        <ChevronDown
          className={cn(
            "h-4 w-4 shrink-0 text-[color:var(--tp-muted)] transition-transform",
            open && "rotate-180",
          )}
        />
      </button>

      {open && <div className="px-4 pb-4 pt-0.5">{children}</div>}
    </li>
  );
}

/**
 * How many rows are showing, and how many there are.
 *
 * Always both numbers when a filter is on. "6 requirements" over a filtered list
 * of 20 is the kind of quiet miscount that makes an approver think they have seen
 * everything.
 */
export function ShowingCount({
  showing,
  total,
  noun,
  onClear,
}: {
  showing: number;
  total: number;
  noun: string;
  onClear?: () => void;
}) {
  const filtered = showing !== total;
  return (
    <p className="tp-den flex flex-wrap items-center gap-2">
      <span>
        {filtered ? `Showing ${showing} of ${total} ${noun}` : `${total} ${noun}`}
      </span>
      {filtered && onClear && (
        <button
          type="button"
          onClick={onClear}
          className="font-medium text-blue-600 underline-offset-2 hover:underline dark:text-blue-300"
        >
          Clear filters
        </button>
      )}
    </p>
  );
}

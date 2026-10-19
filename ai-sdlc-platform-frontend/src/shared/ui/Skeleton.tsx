import { cn } from "@/shared/utils/cn";

/**
 * The place of something that is on its way, drawn in its shape.
 *
 * For a list whose rows are known before its data is: the page keeps its
 * layout and does not read as empty. A lone wait still takes the spinner
 * (`PageLoader`). Decorative: the group around it carries the status and its
 * label, once, not every block. It pulses only where motion is welcome.
 */
export function Skeleton({ className }: { className?: string }) {
  return <div aria-hidden="true" className={cn("rounded-md bg-slate-400/20 motion-safe:animate-pulse", className)} />;
}

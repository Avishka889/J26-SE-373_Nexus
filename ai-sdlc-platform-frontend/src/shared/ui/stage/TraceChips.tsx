import { cn } from "@/shared/utils/cn";

/**
 * The requirement ids an artifact element came from.
 *
 * Traceability is the claim this phase is built on, so it is rendered on every
 * element rather than implied by a diagram somewhere. Clicking a chip opens the
 * requirement it names: one jump, implemented once, used by every stage.
 */
export function TraceChips({
  traces,
  onJump,
  label = "Traces to",
  className,
}: {
  traces: string[];
  onJump: (requirementId: string) => void;
  label?: string;
  className?: string;
}) {
  if (traces.length === 0) return null;

  return (
    <span className={cn("inline-flex flex-wrap items-center gap-1", className)}>
      <span className="tp-den sr-only">{label}</span>
      {traces.map((id) => (
        <button
          key={id}
          type="button"
          onClick={(e) => {
            e.stopPropagation();
            onJump(id);
          }}
          title={`${label} ${id}. Opens the requirement.`}
          className={cn(
            "tp-mono rounded border px-1 py-px text-[10px] font-medium transition-all",
            "border-blue-500/30 bg-blue-500/[0.07] text-blue-600",
            // A button gets `cursor: default` from the preflight, so without this
            // the app's most useful interaction reads as a static tag.
            "cursor-pointer hover:border-blue-500/60 hover:bg-blue-500/15 hover:underline",
            "focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-1 focus-visible:outline-blue-500",
            "dark:text-blue-300",
          )}
        >
          {id}
        </button>
      ))}
    </span>
  );
}

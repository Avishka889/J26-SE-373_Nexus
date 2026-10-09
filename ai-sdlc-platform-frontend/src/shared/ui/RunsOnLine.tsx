import { Link } from "react-router-dom";
import { Brain } from "lucide-react";
import { cn } from "@/shared/utils/cn";

/**
 * What a send from a chat box runs on: the model and how hard it thinks, as
 * other chat tools name their model in the box, with a link to where the level
 * is chosen where it can be. It wraps rather than truncating, so nothing in it
 * is cut off.
 */
export function RunsOnLine({
  runsOn,
  className,
}: {
  runsOn: { text: string; to?: string };
  /** Size and colour, which differ between the phase pages and the start screens. */
  className: string;
}) {
  return (
    <p className={cn("flex flex-wrap items-center gap-x-1.5 leading-relaxed", className)}>
      <Brain className="h-3 w-3 shrink-0" aria-hidden />
      <span className="min-w-0 break-words">{runsOn.text}</span>
      {runsOn.to && (
        <Link
          to={runsOn.to}
          aria-label="Choose how hard each phase thinks, in Settings"
          className="font-medium text-blue-700 underline-offset-2 hover:underline dark:text-blue-300"
        >
          Settings
        </Link>
      )}
    </p>
  );
}

import { AlertTriangle } from "lucide-react";
import { Badge } from "@/shared/ui/primitives";

/**
 * The project's current phase stopped before its run finished.
 *
 * Beside the status rather than instead of it, so the phase stays named: the
 * project's own page says why the run stopped and offers to go on.
 */
export function RunStoppedChip() {
  return (
    <Badge
      variant="error"
      title="The last run in this phase stopped before it finished. Open the project to continue it or start over."
    >
      <AlertTriangle className="h-3 w-3" aria-hidden="true" />
      Run stopped
    </Badge>
  );
}

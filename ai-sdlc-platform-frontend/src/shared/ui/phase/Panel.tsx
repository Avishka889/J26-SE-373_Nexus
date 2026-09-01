import type { ReactNode } from "react";
import { cn } from "@/shared/utils/cn";
import {
  Card,
  CardContent,
  CardHeader,
  CardTitle,
} from "@/shared/ui/primitives";

/** The app's Card, with the header slots a phase panel needs. */
export function Panel({
  icon,
  label,
  title,
  meta,
  action,
  children,
  className,
  bodyClassName,
}: {
  icon?: ReactNode;
  label?: string;
  title?: ReactNode;
  meta?: ReactNode;
  action?: ReactNode;
  /** Optional, so a panel can be a caption on its own. */
  children?: ReactNode;
  className?: string;
  bodyClassName?: string;
}) {
  return (
    <Card className={className}>
      {(label || title || action) && (
        <CardHeader className={children == null ? "border-b-0" : undefined}>
          {/* A flex basis on the title, so the row wraps rather than crushing it.

              `flex-1 min-w-0` alone lets the title shrink to nothing, so a wide
              action group stays on the row and the heading collapses to one word
              per line beneath it. The sequence diagram card was the first with an
              action wide enough to show it: a use case select, a Diagram/Source
              toggle and an expand control. A flex basis gives the title a
              preferred width, which is what makes flex-wrap move the action to
              its own line instead. min-w-0 stays so long words still truncate.

              The action is min-w-0 rather than shrink-0. shrink-0 gave it an
              unbounded width, so its own flex-wrap never fired: at 390 the UML
              card's action (a use case select, a Diagram/Source toggle and an
              expand control) stayed 418px wide inside a 374px column and scrolled
              the stage sideways. basis-64 above is what moves it to its own line,
              so it does not need shrink-0 to get there, and once it is alone on a
              line it must be free to shrink. */}
          <div className="flex flex-wrap items-start justify-between gap-x-4 gap-y-2">
            <div className="min-w-0 flex-1 basis-64">
              {label && (
                <CardTitle className="flex items-center gap-2">
                  {icon}
                  {label}
                </CardTitle>
              )}
              {title && (
                <p className="mt-1 text-xs text-[color:var(--tp-ink-2)]">
                  {title}
                </p>
              )}
              {meta && <p className="tp-den mt-1">{meta}</p>}
            </div>
            {action && <div className="min-w-0">{action}</div>}
          </div>
        </CardHeader>
      )}
      {children != null && (
        <CardContent className={bodyClassName}>{children}</CardContent>
      )}
    </Card>
  );
}

export function Hairline({ className }: { className?: string }) {
  return (
    <div className={cn("h-px w-full bg-[color:var(--tp-line)]", className)} />
  );
}

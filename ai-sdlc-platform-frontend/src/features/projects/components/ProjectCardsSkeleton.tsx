import { Card, CardContent } from "@/shared/ui/primitives";
import { Skeleton } from "@/shared/ui/Skeleton";
import { cn } from "@/shared/utils/cn";

/**
 * Project cards that are still being read, in the cards' own places.
 *
 * One spinner where the cards go sat below the fold on Home, and the page read
 * as a workspace with nothing in it.
 */
export function ProjectCardsSkeleton({ count = 3, className }: { count?: number; className?: string }) {
  return (
    <div role="status" aria-label="Loading your projects" className={cn("grid grid-cols-1 gap-4", className)}>
      {Array.from({ length: count }, (_, i) => (
        <Card key={i} data-skeleton-card className="overflow-hidden">
          <Skeleton className="h-24 rounded-none" />
          <CardContent className="space-y-3 p-4">
            <Skeleton className="h-4 w-2/3" />
            <Skeleton className="h-3 w-full" />
            <Skeleton className="h-1.5 w-full rounded-full" />
            <Skeleton className="h-3 w-1/3" />
          </CardContent>
        </Card>
      ))}
    </div>
  );
}

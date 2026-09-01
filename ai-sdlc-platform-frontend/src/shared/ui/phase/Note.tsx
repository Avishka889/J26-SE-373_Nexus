import type { ReactNode } from "react";
import { cn } from "@/shared/utils/cn";

export function Note({ children, className }: { children: ReactNode; className?: string }) {
  return <p className={cn("tp-prose", className)}>{children}</p>;
}

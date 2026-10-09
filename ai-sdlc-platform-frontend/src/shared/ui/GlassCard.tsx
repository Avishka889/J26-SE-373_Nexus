import type { HTMLAttributes } from "react";
import { cn } from "@/shared/utils/cn";

export function GlassCard({ className, children, ...props }: HTMLAttributes<HTMLDivElement>) {
  return (
    <div
      className={cn(
        "group rounded-2xl border border-white/60 bg-white/70 shadow-xl shadow-blue-900/[0.04] backdrop-blur-xl",
        "transition-all duration-300 hover:border-blue-200/60 hover:shadow-2xl hover:shadow-blue-900/[0.06]",
        className
      )}
      {...props}
    >
      {children}
    </div>
  );
}

import { type ReactNode } from "react";
import { CheckCircle2, type LucideIcon } from "lucide-react";
import type { ConnectionStatus } from "../model/connection";
import { useUiStore } from "@/store/ui";
import { cn } from "@/shared/utils/cn";
import { Badge } from "@/shared/ui/primitives";

export function SettingsPanel({
  icon: Icon,
  title,
  description,
  status,
  children,
  footer,
}: {
  icon: LucideIcon;
  title: string;
  description: string;
  /** What the panel's stored credential is known to do, from its last check. */
  status?: ConnectionStatus;
  children: ReactNode;
  footer?: ReactNode;
}) {
  const theme = useUiStore((s) => s.theme);
  const isDark = theme === "dark";

  return (
    <section
      className={cn(
        "overflow-hidden rounded-2xl border backdrop-blur-sm",
        isDark
          ? "border-white/[0.08] bg-[#0f1d32]/60"
          : "border-slate-200/80 bg-white/90 shadow-sm shadow-slate-200/50",
      )}
    >
      <div
        className={cn(
          "flex flex-wrap items-start justify-between gap-4 border-b px-6 py-5",
          isDark
            ? "border-white/[0.06] bg-white/[0.02]"
            : "border-slate-100 bg-slate-50/50",
        )}
      >
        <div className="flex items-start gap-4">
          <div className="flex h-11 w-11 shrink-0 items-center justify-center rounded-xl bg-blue-600 shadow-lg shadow-blue-600/20">
            <Icon className="h-5 w-5 text-white" />
          </div>
          <div>
            <h3
              className={cn(
                "text-base font-semibold tracking-tight",
                isDark ? "text-white" : "text-slate-900",
              )}
            >
              {title}
            </h3>
            <p
              className={cn(
                "mt-0.5 text-sm",
                isDark ? "text-slate-400" : "text-slate-500",
              )}
            >
              {description}
            </p>
          </div>
        </div>
        {status && (
          <Badge variant={status.tone} className="px-2.5 py-1 text-xs">
            {status.tone === "success" && <CheckCircle2 className="h-3.5 w-3.5" />}
            {status.label}
          </Badge>
        )}
      </div>

      <div className="space-y-6 px-6 py-6">{children}</div>

      {footer && (
        <div
          className={cn(
            "flex flex-wrap items-center gap-3 border-t px-6 py-4",
            isDark
              ? "border-white/[0.06] bg-white/[0.02]"
              : "border-slate-100 bg-slate-50/30",
          )}
        >
          {footer}
        </div>
      )}
    </section>
  );
}

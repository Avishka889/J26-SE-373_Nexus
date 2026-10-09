import { cn } from "@/shared/utils/cn";

/**
 * Theme-aware Tailwind class tokens shared across app features.
 * Prefer these over repeating `isDark ? "border-white/10..." : "border-slate-200..."` ternaries.
 */
export const surface = {
  border: (isDark: boolean) => (isDark ? "border-white/10" : "border-slate-200"),
  divider: (isDark: boolean) => (isDark ? "border-white/[0.05]" : "border-slate-100"),
  panel: (isDark: boolean) =>
    isDark ? "border-white/10 bg-white/[0.03]" : "border-slate-200 bg-white",
  inset: (isDark: boolean) =>
    isDark ? "border-white/10 bg-white/[0.02]" : "border-slate-200 bg-slate-50",
  raised: (isDark: boolean) =>
    isDark ? "border-white/10 bg-white/[0.04]" : "border-slate-200 bg-white",
  modal: (isDark: boolean) =>
    isDark ? "border border-white/10 bg-[#0f172a]" : "border border-slate-200 bg-white",
  dashed: (isDark: boolean) =>
    isDark ? "border-white/10 text-slate-400" : "border-slate-200 text-slate-500",
  /** Border, background and text for a failed or danger state; same red as the Badge and Button `error` variants in primitives.tsx. */
  danger: (isDark: boolean) =>
    isDark
      ? "border-red-500/20 bg-red-500/10 text-red-400"
      : "border-red-200/80 bg-red-50 text-red-700",
  heading: (isDark: boolean) => (isDark ? "text-white" : "text-slate-900"),
  body: (isDark: boolean) => (isDark ? "text-slate-300" : "text-slate-600"),
  muted: (isDark: boolean) => (isDark ? "text-slate-400" : "text-slate-500"),
  faint: (isDark: boolean) => (isDark ? "text-slate-400" : "text-slate-500"),
  iconGhost: (isDark: boolean) =>
    cn(
      "flex h-9 w-9 items-center justify-center rounded-xl transition-colors",
      isDark ? "text-slate-400 hover:bg-white/5" : "text-slate-500 hover:bg-slate-100"
    ),
  softChip: (isDark: boolean) =>
    cn(
      "shrink-0 rounded-full border px-3 py-1.5 text-xs transition-colors",
      isDark
        ? "border-white/10 text-slate-400 hover:bg-white/5 hover:text-slate-200"
        : "border-slate-200 bg-white/80 text-slate-500 hover:border-slate-300 hover:text-slate-700"
    ),
  starterChip: (isDark: boolean) =>
    cn(
      "flex shrink-0 items-center gap-2 rounded-full border px-3.5 py-2 text-xs font-medium transition-all active:scale-[0.98] sm:hover:-translate-y-0.5",
      isDark
        ? "border-white/10 bg-white/[0.03] text-slate-300 hover:bg-white/[0.06]"
        : "border-slate-200 bg-white text-slate-600 shadow-sm hover:border-slate-300"
    ),
  field: (isDark: boolean) =>
    cn(
      "h-11 w-full rounded-xl border px-3.5 text-sm outline-none transition-all",
      "focus:border-blue-500/50 focus:ring-2 focus:ring-blue-500/20",
      isDark
        ? "border-white/10 bg-white/[0.04] text-white placeholder:text-slate-400"
        : "border-slate-200 bg-white text-slate-900 placeholder:text-slate-500"
    ),
  textArea: (isDark: boolean) =>
    cn(
      "min-h-[88px] w-full resize-y rounded-xl border px-3.5 py-3 text-sm outline-none transition-all",
      "focus:border-blue-500/50 focus:ring-2 focus:ring-blue-500/20",
      isDark
        ? "border-white/10 bg-white/[0.04] text-white placeholder:text-slate-400"
        : "border-slate-200 bg-white text-slate-900 placeholder:text-slate-500"
    ),
} as const;

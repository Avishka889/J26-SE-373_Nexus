import type { ActivityLogCategory } from "../fixtures/activityData";
import { categories } from "./categories";
import { cn } from "@/shared/utils/cn";

export function ActivityFilters({
  filter,
  onFilterChange,
  isDark,
}: {
  filter: ActivityLogCategory | "all";
  onFilterChange: (filter: ActivityLogCategory | "all") => void;
  isDark: boolean;
}) {
  return (
    <div role="group" aria-label="Show events of" className="mb-6 flex flex-wrap gap-2">
      {categories.map((cat) => (
        <button
          key={cat.id}
          type="button"
          aria-pressed={filter === cat.id}
          onClick={() => onFilterChange(cat.id)}
          className={cn(
            "rounded-full border px-3 py-1 text-xs font-medium transition-colors",
            filter === cat.id
              ? isDark
                ? "border-blue-500/40 bg-blue-500/10 text-blue-300"
                : "border-blue-200 bg-blue-50 text-blue-700"
              : isDark
                ? "border-white/10 text-slate-400 hover:bg-white/[0.04]"
                : "border-slate-200 text-slate-500 hover:bg-slate-50"
          )}
        >
          {cat.label}
        </button>
      ))}
    </div>
  );
}

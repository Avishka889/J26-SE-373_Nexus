import { Check } from "lucide-react";
import { useIsDark } from "@/shared/theme";
import { cn } from "@/shared/utils/cn";
import type { SaveState } from "../useDebouncedText";

const WORDS: Record<Exclude<SaveState, "idle">, string> = {
  saving: "Saving...",
  saved: "Saved",
  failed: "Not saved",
};

/**
 * What became of an edit to a setting that saves as it is made.
 *
 * The settings tabs have no Save button, so the field says it, under itself:
 * they saved without a word, and nothing said whether a change was kept.
 * Nothing shows until the field is edited.
 */
export function SaveStatus({ state }: { state: SaveState }) {
  const isDark = useIsDark();
  if (state === "idle") return null;
  return (
    <p
      role="status"
      className={cn(
        "mt-1.5 flex items-center gap-1.5 text-xs",
        state === "failed"
          ? isDark
            ? "text-red-400"
            : "text-red-600"
          : state === "saved"
            ? isDark
              ? "text-emerald-400"
              : "text-emerald-700"
            : isDark
              ? "text-slate-400"
              : "text-slate-500",
      )}
    >
      {state === "saved" && <Check aria-hidden="true" className="h-3.5 w-3.5" />}
      {WORDS[state]}
    </p>
  );
}

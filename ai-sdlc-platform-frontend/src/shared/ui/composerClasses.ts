import { cn } from "@/shared/utils/cn";

/**
 * The textarea styling both composers share.
 *
 * A plain function, so it lives beside the composer components rather than
 * inside their module: mixing the two costs hot reload for every component in
 * the file.
 */
export function composerTextareaClass(isDark: boolean) {
  return cn(
    "w-full resize-none bg-transparent text-[15px] leading-relaxed outline-none placeholder:text-slate-400",
    isDark ? "text-slate-100" : "text-slate-800"
  );
}

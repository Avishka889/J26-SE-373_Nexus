import { useIsDark } from "@/shared/theme";
import { surface } from "./surface";

/**
 * The input classes every form field shares.
 *
 * Kept out of `Field.tsx` because a file that exports both a component and a
 * hook cannot hot reload: the component's state resets on every edit to the
 * hook. Same module before, same barrel export now.
 */
export function useFieldClasses() {
  const isDark = useIsDark();
  return {
    isDark,
    fieldClass: surface.field(isDark),
    textAreaClass: surface.textArea(isDark),
  };
}

import { useContext } from "react";
import { ThemeContext } from "./ThemeContext";
import type { Theme } from "@/types/ui";

/** Prefer this in shared/, which may never import Zustand stores. */
export function useTheme(): Theme {
  return useContext(ThemeContext);
}

export function useIsDark(): boolean {
  return useTheme() === "dark";
}

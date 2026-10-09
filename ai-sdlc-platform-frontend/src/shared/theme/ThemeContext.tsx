import { createContext, type ReactNode } from "react";
import type { Theme } from "@/types/ui";

const ThemeContext = createContext<Theme>("light");

export function ThemeProvider({ theme, children }: { theme: Theme; children: ReactNode }) {
  return <ThemeContext.Provider value={theme}>{children}</ThemeContext.Provider>;
}

export { ThemeContext };

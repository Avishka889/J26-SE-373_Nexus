/**
 * UI prefs slice: theme, sidebar, toasts, command palette.
 * Server entity caches do not belong here: use TanStack Query.
 */

import { create } from "zustand";
import { persist } from "zustand/middleware";
import type { Theme } from "@/types/ui";

export type { Theme };
export interface Toast {
  id: string;
  type: "success" | "error" | "warning" | "info";
  title: string;
  message?: string;
}

/** How long each kind of notice stays, in milliseconds; null is until dismissed. */
const TOAST_LASTS: Record<Toast["type"], number | null> = {
  success: 4000,
  info: 4000,
  warning: 8000,
  error: null,
};

function applyTheme(theme: Theme) {
  if (typeof document === "undefined") return;
  document.documentElement.classList.toggle("dark", theme === "dark");
  document.documentElement.classList.toggle("light", theme === "light");
  localStorage.setItem("sdlc-theme", theme);
}

const getInitialTheme = (): Theme => {
  if (typeof window !== "undefined") {
    const saved = localStorage.getItem("sdlc-theme");
    if (saved === "light" || saved === "dark") return saved;
  }
  return "light";
};

const initialTheme = getInitialTheme();
applyTheme(initialTheme);

export interface UiState {
  theme: Theme;
  sidebarCollapsed: boolean;
  /**
   * Whether the phase conversation panel is open.
   *
   * A preference rather than page state: a reader who closes it to get width
   * back means it for the next stage and the next project too, so it is
   * remembered like the sidebar.
   *
   * Entering a new project's requirements closes it (`useCreateFromPrompt`, and
   * the requirements page's own start): the run fills the stages first, and
   * the reader opens it from its toggle, which counts the questions waiting,
   * when there is something to answer.
   */
  conversationOpen: boolean;
  /**
   * Whether the phone sheet is open. Separate from `conversationOpen` and never
   * persisted: the sheet covers the whole screen, so "remembered like the
   * sidebar" meant a fresh visit at phone width opened on top of the work. The
   * desk column keeps the preference; the sheet is opened per visit, by the
   * toggle, and starts closed.
   */
  conversationSheetOpen: boolean;
  commandPaletteOpen: boolean;
  toasts: Toast[];
  setTheme: (theme: Theme) => void;
  toggleTheme: () => void;
  toggleSidebar: () => void;
  setConversationOpen: (open: boolean) => void;
  setConversationSheetOpen: (open: boolean) => void;
  toggleConversation: () => void;
  setCommandPaletteOpen: (open: boolean) => void;
  addToast: (toast: Omit<Toast, "id">) => void;
  /** @deprecated use addToast */
  pushToast: (toast: Omit<Toast, "id">) => void;
  removeToast: (id: string) => void;
  dismissToast: (id: string) => void;
}

export const useUiStore = create<UiState>()(
  persist(
    (set, get) => {
      // An error stays until it is dismissed: it went after four seconds,
      // often before it was read, and with it the only word of what failed.
      // The same notice raised again replaces the one showing rather than
      // stacking a copy of it.
      const addToast = (toast: Omit<Toast, "id">) => {
        const id = Math.random().toString(36).slice(2);
        set((s) => ({
          toasts: [
            ...s.toasts.filter(
              (t) =>
                t.type !== toast.type ||
                t.title !== toast.title ||
                t.message !== toast.message,
            ),
            { ...toast, id },
          ],
        }));
        const lasts = TOAST_LASTS[toast.type];
        if (lasts === null) return;
        setTimeout(() => {
          set((s) => ({ toasts: s.toasts.filter((t) => t.id !== id) }));
        }, lasts);
      };

      return {
        theme: initialTheme,
        sidebarCollapsed: false,
        conversationOpen: true,
        conversationSheetOpen: false,
        commandPaletteOpen: false,
        toasts: [],
        setTheme: (theme) => {
          applyTheme(theme);
          set({ theme });
        },
        toggleTheme: () => {
          const theme = get().theme === "dark" ? "light" : "dark";
          applyTheme(theme);
          set({ theme });
        },
        toggleSidebar: () =>
          set((s) => ({ sidebarCollapsed: !s.sidebarCollapsed })),
        setConversationOpen: (conversationOpen) => set({ conversationOpen }),
        setConversationSheetOpen: (conversationSheetOpen) =>
          set({ conversationSheetOpen }),
        toggleConversation: () =>
          set((s) => ({ conversationOpen: !s.conversationOpen })),
        setCommandPaletteOpen: (commandPaletteOpen) =>
          set({ commandPaletteOpen }),
        addToast,
        pushToast: addToast,
        removeToast: (id) =>
          set((s) => ({ toasts: s.toasts.filter((t) => t.id !== id) })),
        dismissToast: (id) =>
          set((s) => ({ toasts: s.toasts.filter((t) => t.id !== id) })),
      };
    },
    {
      name: "nexus-ui",
      partialize: (state) => ({
        theme: state.theme,
        sidebarCollapsed: state.sidebarCollapsed,
        conversationOpen: state.conversationOpen,
      }),
      onRehydrateStorage: () => (state) => {
        if (state?.theme) applyTheme(state.theme);
      },
    },
  ),
);

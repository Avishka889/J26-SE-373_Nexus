/**
 * Session slice: auth flags and active project id.
 * Persist only non-sensitive fields, never tokens or API keys.
 */

import { isLive } from "@/lib/env";
import { create } from "zustand";
import { persist } from "zustand/middleware";

export interface SessionState {
  isAuthenticated: boolean;
  activeProjectId: string | null;
  displayName: string | null;
  login: () => void;
  logout: () => void;
  setAuthenticated: (value: boolean) => void;
  setActiveProjectId: (id: string | null) => void;
  setDisplayName: (name: string | null) => void;
  clearSession: () => void;
}

export const useSessionStore = create<SessionState>()(
  persist(
    (set) => ({
      isAuthenticated: false,
      // The demo's first project on fixtures; nothing in the running app, whose
      // project ids are the server's.
      activeProjectId: isLive("projects") ? null : "p1",
      displayName: null,
      login: () => set({ isAuthenticated: true }),
      logout: () =>
        set({
          isAuthenticated: false,
          activeProjectId: null,
          displayName: null,
        }),
      setAuthenticated: (isAuthenticated) => set({ isAuthenticated }),
      setActiveProjectId: (activeProjectId) => set({ activeProjectId }),
      setDisplayName: (displayName) => set({ displayName }),
      clearSession: () =>
        set({
          isAuthenticated: false,
          activeProjectId: null,
          displayName: null,
        }),
    }),
    {
      name: "nexus-session",
      partialize: (state) => ({
        isAuthenticated: state.isAuthenticated,
        activeProjectId: state.activeProjectId,
        displayName: state.displayName,
      }),
    },
  ),
);

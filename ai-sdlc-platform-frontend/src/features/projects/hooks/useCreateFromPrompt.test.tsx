import type { ReactNode } from "react";
import { act, renderHook } from "@testing-library/react";
import { MemoryRouter, useLocation } from "react-router-dom";
import { describe, expect, it, vi } from "vitest";
import { useUiStore } from "@/store/ui";
import { useCreateFromPrompt } from "./useCreateFromPrompt";

vi.mock("./useProjectsApi", () => ({
  useProjectMutations: () => ({
    createProjectSync: vi.fn(async () => ({ id: "p9" })),
  }),
}));

function wrapper({ children }: { children: ReactNode }) {
  return <MemoryRouter initialEntries={["/"]}>{children}</MemoryRouter>;
}

/**
 * The prompt on Home and on New project opens the new project's design with the
 * conversation closed: the run fills the stages first, and the conversation
 * opens from its toggle, which counts the questions waiting. Open, it took a
 * third of the width from the stages the moment a project began.
 */
describe("creating a project from the prompt", () => {
  it("opens its design with the conversation closed", async () => {
    useUiStore.setState({ conversationOpen: true });
    const { result } = renderHook(
      () => ({ create: useCreateFromPrompt(), location: useLocation() }),
      { wrapper },
    );

    await act(() => result.current.create("Track movies.", [], "Track movies."));

    expect(result.current.location.pathname).toBe("/projects/p9/requirements");
    expect(useUiStore.getState().conversationOpen).toBe(false);
  });
});

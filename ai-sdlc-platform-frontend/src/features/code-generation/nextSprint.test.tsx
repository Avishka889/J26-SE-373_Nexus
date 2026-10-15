import { afterAll, afterEach, beforeAll, describe, expect, it, vi } from "vitest";
import { cleanup, render, screen } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter } from "react-router-dom";
import { MOCK_PROJECTS } from "@/entities/project/fixtures";
import { codeApi } from "./api";
import { CodeWorkspace } from "./components/CodeWorkspace";

// The whole page, which watches its sections scroll; jsdom has neither.
const scrollIntoView = Element.prototype.scrollIntoView;
beforeAll(() => {
  vi.stubGlobal(
    "IntersectionObserver",
    class {
      observe() {}
      unobserve() {}
      disconnect() {}
      takeRecords() {
        return [];
      }
    },
  );
  Element.prototype.scrollIntoView = () => {};
});
afterAll(() => {
  vi.unstubAllGlobals();
  Element.prototype.scrollIntoView = scrollIntoView;
});

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

/**
 * C2-10: planning the next sprint while this build's review waited resolved
 * the review as requested changes. The page keeps the next sprint in view and
 * waits for the review, saying why, as the server does.
 */
describe("the next sprint while the code review waits", () => {
  it("is shown, and waits for the review to be decided", async () => {
    const project = MOCK_PROJECTS.find((one) => one.id === "p2")!;
    const base = await codeApi.getCode(project.id);
    vi.spyOn(codeApi, "getCode").mockResolvedValue({
      ...base,
      nextSprint: {
        number: 2,
        stories: [{ id: "US-4", title: "Export a report", points: 8, priority: "should" }],
        points: 8,
        velocity: 20,
        velocityBasis: "assumed, not measured",
      },
      run: {
        id: "run-1",
        state: "awaiting_gate",
        version: base.codeVersion,
        model: "deepseek:deepseek-flash",
        thinking: "disabled",
        startedAt: "2026-10-08T09:00:00+00:00",
        finishedAt: null,
        stoppedAt: null,
        error: null,
      },
    });
    render(
      <QueryClientProvider client={new QueryClient()}>
        <MemoryRouter initialEntries={[`/projects/${project.id}/code?stage=sprint-scope`]}>
          <CodeWorkspace project={project} />
        </MemoryRouter>
      </QueryClientProvider>,
    );

    const plan = (await screen.findByRole("button", {
      name: "Plan sprint 2",
    })) as HTMLButtonElement;
    expect(plan.disabled).toBe(true);
    expect(screen.getByText(/Decide the code review first/)).toBeTruthy();
  });
});

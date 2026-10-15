import { afterAll, afterEach, beforeAll, describe, expect, it, vi } from "vitest";
import { cleanup, render, screen } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter } from "react-router-dom";
import type { PhaseModel } from "@/entities/settings";
import { MOCK_PROJECTS } from "@/entities/project/fixtures";
import { codeApi } from "./api";
import { CodeWorkspace } from "./components/CodeWorkspace";

const phases = vi.hoisted(() => ({ models: [] as PhaseModel[] }));

vi.mock("@/entities/settings/models", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/entities/settings/models")>()),
  phaseModels: vi.fn(async () => phases.models),
}));

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

const FLASH = "deepseek:deepseek-flash";

/**
 * The chat box says what a send runs on. A request for changes at the review
 * regenerates the code in the run that waits there, at the level it started
 * at, so the box names that run's level and the next run's beside it.
 */
describe("the Code Generation chat box", () => {
  async function showWithRun(state: "awaiting_gate" | "done") {
    const project = MOCK_PROJECTS.find((one) => one.id === "p2")!;
    const base = await codeApi.getCode(project.id);
    vi.spyOn(codeApi, "getCode").mockResolvedValue({
      ...base,
      run: {
        id: "run-1",
        state,
        version: base.codeVersion,
        model: FLASH,
        thinking: "disabled",
        startedAt: "2026-10-04T09:00:00+00:00",
        finishedAt: null,
        stoppedAt: null,
        error: null,
      },
    });
    phases.models = [
      {
        phase: "Code Generation",
        key: "code",
        model: FLASH,
        thinking: "high",
        thinkingChosen: true,
        thinkingApplies: true,
      },
    ];
    render(
      <QueryClientProvider client={new QueryClient()}>
        <MemoryRouter initialEntries={[`/projects/${project.id}/code`]}>
          <CodeWorkspace project={project} />
        </MemoryRouter>
      </QueryClientProvider>,
    );
  }

  it("names the waiting run's level while a review waits, and the next run's beside it", async () => {
    await showWithRun("awaiting_gate");

    expect(
      await screen.findByText(`This run: ${FLASH}, thinking off. Next run: thinking on, high effort.`),
    ).toBeTruthy();
  });

  it("names the next run's once nothing waits", async () => {
    await showWithRun("done");

    expect(await screen.findByText(`Next run: ${FLASH}, thinking on, high effort.`)).toBeTruthy();
  });
});
